import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")

HUBSPOT_TOKEN = os.environ.get("HUBSPOT_TOKEN", "")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "")

# Optional shared secret for POST /sync/run on the public deployment.
SYNC_API_KEY = os.environ.get("SYNC_API_KEY", "")

# 0 disables the in-process scheduler; the sync endpoint works either way.
SYNC_INTERVAL_MINUTES = int(os.environ.get("SYNC_INTERVAL_MINUTES", "0") or 0)


def google_credentials_info() -> dict | None:
    """GOOGLE_SERVICE_ACCOUNT_JSON is either a file path or the JSON itself
    (Render env vars can't hold files, so inline JSON has to be allowed)."""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        return json.loads(raw)
    return json.loads(Path(raw).read_text())
