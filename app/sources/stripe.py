"""Stripe source (test mode): charges via the plain REST API.

The cursor is "fetch started at" (unix seconds) minus a minute of overlap,
same idea as the HubSpot source. Amounts are already in the smallest
currency unit so they go straight into amount_cents.
"""

import time
from datetime import datetime, timezone

import httpx

from .. import config
from ..models import Record
from .errors import SourceError, StaleCursor

NAME = "stripe"
BASE = "https://api.stripe.com/v1"
PAGE_SIZE = 100
OVERLAP_S = 60

RAW_KEYS = ("id", "amount", "currency", "status", "refunded", "description", "created", "payment_intent")


def full_fetch() -> tuple[list[Record], str]:
    started = int(time.time())
    with _client() as client:
        records = [_charge(c) for c in _list_charges(client)]
    return records, str(started - OVERLAP_S)


def incremental_fetch(cursor: str) -> tuple[list[Record], str]:
    try:
        since = int(cursor)
    except (TypeError, ValueError):
        raise StaleCursor(f"unusable stripe cursor: {cursor!r}")
    started = int(time.time())
    with _client() as client:
        records = [_charge(c) for c in _list_charges(client, created_gte=since)]
    return records, str(started - OVERLAP_S)


def _client() -> httpx.Client:
    if not config.STRIPE_SECRET_KEY:
        raise SourceError("STRIPE_SECRET_KEY is not configured")
    return httpx.Client(base_url=BASE, auth=(config.STRIPE_SECRET_KEY, ""), timeout=30)


def _list_charges(client, created_gte=None):
    starting_after = None
    while True:
        params = {"limit": PAGE_SIZE}
        if created_gte is not None:
            params["created[gte]"] = created_gte
        if starting_after:
            params["starting_after"] = starting_after
        resp = client.get("/charges", params=params)
        if resp.status_code == 400 and created_gte is not None:
            raise StaleCursor(f"stripe rejected the created filter: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise SourceError(f"stripe API error {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        data = body.get("data", [])
        yield from data
        if not body.get("has_more") or not data:
            break
        starting_after = data[-1]["id"]


def _charge(charge) -> Record:
    # a fully refunded charge still reports status=succeeded, so check the flag
    raw_status = "refunded" if charge.get("refunded") else charge.get("status", "")
    return Record(
        source=NAME,
        source_id=charge["id"],
        kind="payment",
        title=charge.get("description") or f"charge {charge['id']}",
        status=raw_status,
        amount_cents=charge.get("amount"),
        currency=charge.get("currency"),
        occurred_at=datetime.fromtimestamp(charge["created"], tz=timezone.utc),
        raw={k: charge.get(k) for k in RAW_KEYS},
    )
