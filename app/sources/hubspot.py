"""HubSpot CRM source: contacts and deals, via a private app token.

Incremental sync uses the CRM search API filtered on last-modified time.
The cursor we store is "fetch started at" (epoch ms) minus a minute of
overlap. Re-reading a sliver of already-seen records is harmless because
writes are idempotent, and the overlap means records modified while a
fetch was in flight are never missed.
"""

import logging
import time
from datetime import datetime

import httpx

from .. import config
from ..models import Record
from .errors import SourceError, StaleCursor

NAME = "hubspot"
BASE = "https://api.hubapi.com"
PAGE_SIZE = 100
OVERLAP_MS = 60_000

CONTACT_PROPS = ["firstname", "lastname", "email"]
DEAL_PROPS = ["dealname", "amount", "dealstage", "closedate"]

log = logging.getLogger(__name__)


def full_fetch() -> tuple[list[Record], str]:
    started_ms = int(time.time() * 1000)
    records = []
    with _client() as client:
        records += [_contact(o) for o in _list_all(client, "contacts", CONTACT_PROPS)]
        records += [_deal(o) for o in _list_all(client, "deals", DEAL_PROPS)]
    return records, str(started_ms - OVERLAP_MS)


def incremental_fetch(cursor: str) -> tuple[list[Record], str]:
    try:
        since_ms = int(cursor)
    except (TypeError, ValueError):
        raise StaleCursor(f"unusable hubspot cursor: {cursor!r}")
    started_ms = int(time.time() * 1000)
    records = []
    with _client() as client:
        records += [
            _contact(o)
            for o in _search_since(client, "contacts", "lastmodifieddate", since_ms, CONTACT_PROPS)
        ]
        records += [
            _deal(o)
            for o in _search_since(client, "deals", "hs_lastmodifieddate", since_ms, DEAL_PROPS)
        ]
    return records, str(started_ms - OVERLAP_MS)


def _client() -> httpx.Client:
    if not config.HUBSPOT_TOKEN:
        raise SourceError("HUBSPOT_TOKEN is not configured")
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"Bearer {config.HUBSPOT_TOKEN}"},
        timeout=30,
    )


def _list_all(client, obj, props):
    after = None
    while True:
        params = {"limit": PAGE_SIZE, "properties": ",".join(props)}
        if after:
            params["after"] = after
        resp = client.get(f"/crm/v3/objects/{obj}", params=params)
        _check(resp, obj)
        body = resp.json()
        yield from body.get("results", [])
        after = body.get("paging", {}).get("next", {}).get("after")
        if not after:
            break


def _search_since(client, obj, ts_prop, since_ms, props):
    after = None
    while True:
        body = {
            "filterGroups": [
                {"filters": [{"propertyName": ts_prop, "operator": "GT", "value": str(since_ms)}]}
            ],
            "sorts": [{"propertyName": ts_prop, "direction": "ASCENDING"}],
            "properties": props,
            "limit": PAGE_SIZE,
        }
        if after:
            body["after"] = after
        resp = client.post(f"/crm/v3/objects/{obj}/search", json=body)
        if resp.status_code == 400:
            # HubSpot refused the filter value; treat the cursor as dead
            raise StaleCursor(f"hubspot rejected the {obj} search cursor: {resp.text[:200]}")
        _check(resp, obj)
        data = resp.json()
        yield from data.get("results", [])
        after = data.get("paging", {}).get("next", {}).get("after")
        if not after:
            break


def _check(resp, obj):
    if resp.status_code >= 400:
        raise SourceError(f"hubspot {obj} API error {resp.status_code}: {resp.text[:200]}")


def _contact(obj) -> Record:
    props = obj.get("properties") or {}
    name = " ".join(p for p in (props.get("firstname"), props.get("lastname")) if p)
    return Record(
        source=NAME,
        source_id=f"contact:{obj['id']}",
        kind="contact",
        title=name or props.get("email") or f"contact {obj['id']}",
        status="archived" if obj.get("archived") else "active",
        occurred_at=_parse_ts(obj.get("updatedAt")),
        raw={**props, "id": obj["id"]},
    )


def _deal(obj) -> Record:
    props = obj.get("properties") or {}
    amount_cents = None
    if props.get("amount"):
        try:
            amount_cents = round(float(props["amount"]) * 100)
        except ValueError:
            log.warning("hubspot deal %s has a non-numeric amount: %r", obj["id"], props["amount"])
    return Record(
        source=NAME,
        source_id=f"deal:{obj['id']}",
        kind="deal",
        title=props.get("dealname") or f"deal {obj['id']}",
        status=(props.get("dealstage") or "").lower(),
        amount_cents=amount_cents,
        currency="usd",  # single-currency portal; HubSpot doesn't return one per deal by default
        occurred_at=_parse_ts(props.get("closedate")) or _parse_ts(obj.get("updatedAt")),
        raw={**props, "id": obj["id"]},
    )


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
