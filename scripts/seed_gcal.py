"""Insert a few events into the shared Google Calendar.

The service account needs "Make changes to events" access on the calendar
(share the calendar with the service account's email address).
"""

from datetime import datetime, timedelta, timezone

import httpx

from app import config
from app.sources import gcal

EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events"

# (summary, days from now)
EVENTS = [
    ("Kickoff call - Acme Co", 1),
    ("Product demo - Globex", 2),
    ("Invoice review - Initech", 3),
    ("Quarterly review - Hooli", 7),
    ("Renewal check-in - Umbrella", 10),
]


def main():
    assert config.GOOGLE_CALENDAR_ID, "set GOOGLE_CALENDAR_ID first"
    token = gcal.access_token([EVENTS_SCOPE])
    client = httpx.Client(
        base_url=f"https://www.googleapis.com/calendar/v3/calendars/{config.GOOGLE_CALENDAR_ID}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )

    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    for summary, days in EVENTS:
        start = base + timedelta(days=days, hours=10)
        resp = client.post(
            "/events",
            json={
                "summary": summary,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
            },
        )
        resp.raise_for_status()
        print(f"created event {summary!r} -> {resp.json()['id']}")


if __name__ == "__main__":
    main()
