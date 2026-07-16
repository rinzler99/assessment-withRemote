"""Sync runner: pulls each source, normalizes, upserts.

The three guarantees the assignment asks for live here:

- Sources are isolated. One source blowing up gets logged into sync_state
  and the loop moves on, so the other two still land their data.
- A stale or rejected cursor (StaleCursor) triggers a full backfill for
  that source instead of crashing or silently losing the window.
- Every write is an ON CONFLICT upsert keyed on the source's own id, so a
  webhook firing twice or the job re-running back-to-back can't produce
  duplicate rows.
"""

import logging

from psycopg.types.json import Json

from . import db
from .models import Record
from .sources import gcal, hubspot, stripe
from .sources.errors import StaleCursor
from .statuses import canonical_status

log = logging.getLogger(__name__)

SOURCES = {mod.NAME: mod for mod in (hubspot, stripe, gcal)}

# record kinds that also produce a row in transactions (problem 2)
MONEY_KINDS = {"payment", "deal"}


def run(only: str | None = None) -> dict:
    results = {}
    with db.connect() as conn:
        for name, source in SOURCES.items():
            if only and name != only:
                continue
            try:
                results[name] = _sync_source(conn, name, source)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                log.exception("sync failed for %s", name)
                _save_state(conn, name, mode="error", error=f"{type(exc).__name__}: {exc}")
                conn.commit()
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return results


def _sync_source(conn, name, source) -> dict:
    cursor = _load_cursor(conn, name)
    mode = "incremental" if cursor else "full"
    if cursor:
        try:
            records, new_cursor = source.incremental_fetch(cursor)
        except StaleCursor as exc:
            log.warning("%s cursor is stale (%s); falling back to full backfill", name, exc)
            mode = "full_backfill"
            records, new_cursor = source.full_fetch()
    else:
        records, new_cursor = source.full_fetch()

    inserted, updated = upsert_records(conn, records)
    txns = upsert_transactions(conn, records)
    _save_state(conn, name, mode=mode, cursor=new_cursor)
    return {
        "ok": True,
        "mode": mode,
        "fetched": len(records),
        "inserted": inserted,
        "updated": updated,
        "transactions": txns,
    }


def upsert_records(conn, records: list[Record]) -> tuple[int, int]:
    inserted = updated = 0
    for r in records:
        row = conn.execute(
            """
            insert into records
                (source, source_id, kind, title, status, amount_cents,
                 currency, occurred_at, raw, last_synced_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            on conflict (source, source_id) do update set
                kind = excluded.kind,
                title = excluded.title,
                status = excluded.status,
                amount_cents = excluded.amount_cents,
                currency = excluded.currency,
                occurred_at = excluded.occurred_at,
                raw = excluded.raw,
                last_synced_at = now()
            returning (xmax = 0) as inserted
            """,
            (r.source, r.source_id, r.kind, r.title, r.status,
             r.amount_cents, r.currency, r.occurred_at, Json(r.raw)),
        ).fetchone()
        if row["inserted"]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def upsert_transactions(conn, records: list[Record]) -> int:
    count = 0
    for r in records:
        if r.kind not in MONEY_KINDS or r.amount_cents is None:
            continue
        if r.occurred_at is None:
            log.warning("skipping transaction %s/%s: no usable timestamp", r.source, r.source_id)
            continue
        conn.execute(
            """
            insert into transactions
                (source, source_txn_id, amount_cents, currency,
                 raw_status, canonical_status, occurred_at, last_synced_at)
            values (%s, %s, %s, %s, %s, %s, %s, now())
            on conflict (source, source_txn_id) do update set
                amount_cents = excluded.amount_cents,
                currency = excluded.currency,
                raw_status = excluded.raw_status,
                canonical_status = excluded.canonical_status,
                occurred_at = excluded.occurred_at,
                last_synced_at = now()
            """,
            (r.source, r.source_id, r.amount_cents, r.currency or "usd",
             r.status, canonical_status(r.source, r.status), r.occurred_at),
        )
        count += 1
    return count


def reset_cursor(conn, name: str) -> None:
    conn.execute("update sync_state set sync_cursor = null where source = %s", (name,))


def _load_cursor(conn, name: str) -> str | None:
    row = conn.execute(
        "select sync_cursor from sync_state where source = %s", (name,)
    ).fetchone()
    return row["sync_cursor"] if row else None


def _save_state(conn, name, mode, cursor=None, error=None) -> None:
    # on failure the old cursor is kept (coalesce) so the next run retries
    # the same window instead of skipping it
    conn.execute(
        """
        insert into sync_state (source, sync_cursor, last_mode, last_run_at, last_error)
        values (%s, %s, %s, now(), %s)
        on conflict (source) do update set
            sync_cursor = coalesce(excluded.sync_cursor, sync_state.sync_cursor),
            last_mode = excluded.last_mode,
            last_run_at = now(),
            last_error = excluded.last_error
        """,
        (name, cursor, mode, error),
    )
