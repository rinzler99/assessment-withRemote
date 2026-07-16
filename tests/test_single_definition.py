"""Guard rail: the revenue definition must only ever live in app/metrics.py.

The assignment asks that if someone later adds a second, slightly
different way of computing this number, something actually catches it.
This test is that something: it fails and names the file if any other
module under app/ starts summing transaction amounts or declares its own
status allow-list.
"""

import re
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

PATTERNS = [
    re.compile(r"sum\s*\(\s*amount_cents", re.IGNORECASE),
    re.compile(r"COLLECTED_STATUSES\s*="),
]


def test_revenue_math_only_lives_in_metrics():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.name == "metrics.py":
            continue
        text = path.read_text()
        for pattern in PATTERNS:
            if pattern.search(text):
                offenders.append(f"{path.relative_to(APP_DIR.parent)} matches {pattern.pattern!r}")
    assert not offenders, (
        "revenue definition duplicated outside app/metrics.py:\n  " + "\n  ".join(offenders)
    )
