"""Google Calendar source, using a service account and the events syncToken.

This is the source with a genuinely expiring cursor: the Calendar API
returns 410 GONE when a syncToken is too old, and per Google's docs the
only recovery is to drop the token and re-list everything. That maps
directly onto the runner's StaleCursor -> full backfill path. A malformed
token comes back as a 400, which gets the same treatment since a backfill
is the safe recovery either way.
"""

from datetime import datetime, timezone

import google.auth.transport.requests
import httpx
from google.oauth2 import service_account

from .. import config
from ..models import Record
from .errors import SourceError, StaleCursor

NAME = "gcal"
READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
PAGE_SIZE = 100

RAW_KEYS = ("id", "status", "summary", "start", "end", "updated")


def full_fetch() -> tuple[list[Record], str | None]:
    return _fetch()


def incremental_fetch(cursor: str) -> tuple[list[Record], str | None]:
    return _fetch(sync_token=cursor)


def access_token(scopes: list[str]) -> str:
    info = config.google_credentials_info()
    if not info:
        raise SourceError("GOOGLE_SERVICE_ACCOUNT_JSON is not configured")
    creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _client() -> httpx.Client:
    if not config.GOOGLE_CALENDAR_ID:
        raise SourceError("GOOGLE_CALENDAR_ID is not configured")
    return httpx.Client(
        base_url=f"https://www.googleapis.com/calendar/v3/calendars/{config.GOOGLE_CALENDAR_ID}",
        headers={"Authorization": f"Bearer {access_token([READONLY_SCOPE])}"},
        timeout=30,
    )


def _fetch(sync_token: str | None = None) -> tuple[list[Record], str | None]:
    records: list[Record] = []
    page_token = None
    next_sync_token = None
    with _client() as client:
        while True:
            # showDeleted so cancellations propagate instead of leaving stale rows
            params: dict = {"maxResults": PAGE_SIZE, "showDeleted": "true"}
            if sync_token:
                params["syncToken"] = sync_token
            if page_token:
                params["pageToken"] = page_token
            resp = client.get("/events", params=params)
            if resp.status_code == 410 or (resp.status_code == 400 and sync_token):
                raise StaleCursor(f"calendar syncToken no longer usable ({resp.status_code})")
            if resp.status_code >= 400:
                raise SourceError(f"calendar API error {resp.status_code}: {resp.text[:200]}")
            body = resp.json()
            records += [_event(e) for e in body.get("items", [])]
            page_token = body.get("nextPageToken")
            if not page_token:
                next_sync_token = body.get("nextSyncToken")
                break
    return records, next_sync_token


def _event(event) -> Record:
    # cancelled events arrive as skeletons: little more than an id and status
    start = event.get("start") or {}
    when = start.get("dateTime") or start.get("date")
    occurred_at = None
    if when:
        occurred_at = datetime.fromisoformat(when.replace("Z", "+00:00"))
        if occurred_at.tzinfo is None:  # all-day events are bare dates
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return Record(
        source=NAME,
        source_id=event["id"],
        kind="event",
        title=event.get("summary") or "(no title)",
        status=event.get("status", ""),
        occurred_at=occurred_at,
        raw={k: event.get(k) for k in RAW_KEYS},
    )
