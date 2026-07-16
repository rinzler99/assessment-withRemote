import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Header, HTTPException, Query

from . import config, db, metrics, sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    if config.SYNC_INTERVAL_MINUTES > 0:
        task = asyncio.create_task(_sync_loop())
    yield
    if task:
        task.cancel()


async def _sync_loop():
    while True:
        try:
            results = await asyncio.to_thread(sync.run)
            log.info("scheduled sync: %s", results)
        except Exception:
            log.exception("scheduled sync crashed; retrying next interval")
        await asyncio.sleep(config.SYNC_INTERVAL_MINUTES * 60)


app = FastAPI(
    title="sync pipeline + revenue metrics",
    description="Backend assignment: multi-source sync (HubSpot, Stripe, Google Calendar) "
    "into one normalized schema, plus a drift-proof revenue metric.",
    lifespan=lifespan,
)


@app.get("/health")
def health():
    with db.connect() as conn:
        conn.execute("select 1")
    return {"ok": True}


@app.post("/sync/run")
def sync_run(source: str | None = None, x_api_key: str | None = Header(default=None)):
    if config.SYNC_API_KEY and x_api_key != config.SYNC_API_KEY:
        raise HTTPException(401, "bad or missing x-api-key")
    if source and source not in sync.SOURCES:
        raise HTTPException(400, f"unknown source {source!r}; expected one of {sorted(sync.SOURCES)}")
    return sync.run(only=source)


@app.get("/sync/status")
def sync_status():
    with db.connect() as conn:
        state = conn.execute("select * from sync_state order by source").fetchall()
        counts = conn.execute(
            """
            select source, kind, count(*)::int as records
            from records group by source, kind order by source, kind
            """
        ).fetchall()
    return {"sources": state, "record_counts": counts}


@app.get("/records")
def list_records(
    source: str | None = None,
    kind: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    where, params = [], []
    if source:
        where.append("source = %s")
        params.append(source)
    if kind:
        where.append("kind = %s")
        params.append(kind)
    sql = "select source, source_id, kind, title, status, amount_cents, currency, occurred_at from records"
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by occurred_at desc nulls last limit %s"
    params.append(limit)
    with db.connect() as conn:
        return conn.execute(sql, params).fetchall()


@app.get("/metrics/revenue")
def revenue_total(start: date, end: date):
    _check_range(start, end)
    with db.connect() as conn:
        return metrics.revenue_summary(conn, start, end)


@app.get("/metrics/revenue/daily")
def revenue_daily(start: date, end: date):
    _check_range(start, end)
    with db.connect() as conn:
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": metrics.revenue_by_day(conn, start, end),
        }


def _check_range(start: date, end: date):
    if end < start:
        raise HTTPException(400, "end must be on or after start")
