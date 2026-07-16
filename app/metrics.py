"""The one and only definition of "revenue collected".

Both API views -- the summary total and the per-day breakdown -- come out
of revenue_by_day below, and the summary is literally the sum of the daily
rows, so the two cannot disagree no matter what data shows up.

COLLECTED_STATUSES is an allow-list over the *canonical* status: a raw
status nobody has classified yet normalizes to "unknown" (see statuses.py)
and is excluded until someone deliberately maps it.

If a second, slightly different version of this math ever appears
elsewhere in app/, tests/test_single_definition.py fails and names the
offending file.
"""

from datetime import date, datetime, time, timedelta, timezone

# Canonical statuses that count as money actually collected. Add to this
# only after deciding a status genuinely means settled funds.
COLLECTED_STATUSES = ("collected",)


def revenue_by_day(conn, start: date, end: date) -> list[dict]:
    """Collected revenue per UTC day for [start, end] inclusive, by currency."""
    rows = conn.execute(
        """
        select (occurred_at at time zone 'utc')::date as day,
               currency,
               sum(amount_cents)::bigint as amount_cents,
               count(*)::int as transactions
        from transactions
        where canonical_status = any(%s)
          and occurred_at >= %s
          and occurred_at < %s
        group by 1, 2
        order by 1, 2
        """,
        (list(COLLECTED_STATUSES), _day_start(start), _day_start(end + timedelta(days=1))),
    ).fetchall()
    for row in rows:
        row["day"] = row["day"].isoformat()
    return rows


def revenue_summary(conn, start: date, end: date) -> dict:
    days = revenue_by_day(conn, start, end)
    totals: dict[str, dict] = {}
    for row in days:
        bucket = totals.setdefault(row["currency"], {"amount_cents": 0, "transactions": 0})
        bucket["amount_cents"] += row["amount_cents"]
        bucket["transactions"] += row["transactions"]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "collected_statuses": list(COLLECTED_STATUSES),
        "totals": totals,
    }


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)
