"""Running the same batch through the writers twice must change nothing:
same row counts, second pass reports zero inserts. This is the property
that makes duplicate webhooks and back-to-back sync runs safe."""

from datetime import datetime, timezone

from app import sync
from app.models import Record

TS = datetime(2001, 3, 15, 12, 0, tzinfo=timezone.utc)


def _batch():
    return [
        Record(source="stripe", source_id="ch_idem_test_1", kind="payment",
               title="idempotency test charge", status="succeeded",
               amount_cents=5000, currency="usd", occurred_at=TS,
               raw={"id": "ch_idem_test_1"}),
        Record(source="hubspot", source_id="deal:idem-test-1", kind="deal",
               title="idempotency test deal", status="closedwon",
               amount_cents=120000, currency="usd", occurred_at=TS,
               raw={"id": "idem-test-1"}),
        Record(source="gcal", source_id="evt_idem_test_1", kind="event",
               title="idempotency test event", status="confirmed",
               occurred_at=TS, raw={"id": "evt_idem_test_1"}),
    ]


def _counts(conn):
    records = conn.execute(
        "select count(*)::int as n from records where source_id like '%idem%test%'"
    ).fetchone()["n"]
    txns = conn.execute(
        "select count(*)::int as n from transactions where source_txn_id like '%idem%test%'"
    ).fetchone()["n"]
    return records, txns


def test_double_upsert_produces_no_duplicates(conn):
    batch = _batch()

    inserted, updated = sync.upsert_records(conn, batch)
    sync.upsert_transactions(conn, batch)
    assert (inserted, updated) == (3, 0)
    assert _counts(conn) == (3, 2)  # only the payment and the deal carry money

    # same batch again, as if the webhook fired twice
    inserted, updated = sync.upsert_records(conn, batch)
    sync.upsert_transactions(conn, batch)
    assert (inserted, updated) == (0, 3)
    assert _counts(conn) == (3, 2)


def test_reupsert_applies_changes_in_place(conn):
    batch = _batch()
    sync.upsert_records(conn, batch)
    sync.upsert_transactions(conn, batch)

    batch[0].status = "refunded"  # the charge got refunded upstream
    sync.upsert_records(conn, batch)
    sync.upsert_transactions(conn, batch)

    row = conn.execute(
        "select canonical_status from transactions where source_txn_id = 'ch_idem_test_1'"
    ).fetchone()
    assert row["canonical_status"] == "refunded"
    assert _counts(conn) == (3, 2)
