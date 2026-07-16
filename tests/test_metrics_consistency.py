"""The two revenue views must always agree, and only allow-listed statuses
may ever count. Seed data lives in 2001 so real synced data (which is all
recent) can't interfere with the exact-value assertions; everything rolls
back via the conn fixture."""

from datetime import date, datetime, timezone

from app import metrics, sync
from app.models import Record

# (source, id, amount_cents, raw_status, day) -- covers collected/pending/
# refunded/failed plus an unmapped status from a source we've never seen
SEED = [
    ("stripe", "ch_metrics_test_1", 10000, "succeeded", 1),
    ("stripe", "ch_metrics_test_2", 2500, "succeeded", 2),
    ("stripe", "ch_metrics_test_3", 999, "pending", 2),
    ("stripe", "ch_metrics_test_4", 4000, "refunded", 3),
    ("hubspot", "deal:metrics-test-1", 300000, "closedwon", 3),
    ("hubspot", "deal:metrics-test-2", 50000, "closedlost", 4),
    ("newpay", "np_metrics_test_1", 77700, "settled_v2", 2),
]

COLLECTED_TOTAL = 10000 + 2500 + 300000


def _seed(conn):
    records = [
        Record(source=s, source_id=i, kind="payment", title=i, status=status,
               amount_cents=amount, currency="usd",
               occurred_at=datetime(2001, 2, day, 12, 0, tzinfo=timezone.utc))
        for s, i, amount, status, day in SEED
    ]
    sync.upsert_transactions(conn, records)


def test_summary_equals_sum_of_daily(conn):
    _seed(conn)
    ranges = [
        (date(2001, 2, 1), date(2001, 2, 4)),   # whole window
        (date(2001, 2, 2), date(2001, 2, 2)),   # single day
        (date(2001, 1, 1), date(2001, 3, 1)),   # padded with empty days
        (date(2001, 2, 3), date(2001, 2, 28)),  # partial overlap
    ]
    for start, end in ranges:
        summary = metrics.revenue_summary(conn, start, end)
        daily = metrics.revenue_by_day(conn, start, end)
        by_currency = {}
        for row in daily:
            by_currency[row["currency"]] = by_currency.get(row["currency"], 0) + row["amount_cents"]
        got = {c: t["amount_cents"] for c, t in summary["totals"].items()}
        assert got == by_currency, f"views disagree for {start}..{end}"


def test_only_allowlisted_statuses_count(conn):
    _seed(conn)
    summary = metrics.revenue_summary(conn, date(2001, 2, 1), date(2001, 2, 28))
    # pending, refunded, closedlost and the unmapped settled_v2 (77700)
    # must all be excluded
    assert summary["totals"]["usd"]["amount_cents"] == COLLECTED_TOTAL
    assert summary["totals"]["usd"]["transactions"] == 3


def test_empty_range_is_zero_not_error(conn):
    _seed(conn)
    summary = metrics.revenue_summary(conn, date(2001, 6, 1), date(2001, 6, 30))
    assert summary["totals"] == {}
    assert metrics.revenue_by_day(conn, date(2001, 6, 1), date(2001, 6, 30)) == []
