"""Per-source status vocabularies mapped onto one canonical set.

This is deliberately an allow-list. A status a source starts sending
tomorrow that isn't listed here comes out as "unknown", which the metrics
layer never counts as revenue. The failure mode of an exclusion list --
new statuses silently counting as money -- can't happen.
"""

CANONICAL = {"collected", "pending", "failed", "refunded", "void", "unknown"}

STATUS_MAP = {
    "stripe": {
        "succeeded": "collected",
        "paid": "collected",
        "pending": "pending",
        "failed": "failed",
        "refunded": "refunded",
    },
    "hubspot": {
        "closedwon": "collected",
        "closedlost": "failed",
        # open pipeline stages: money not in the bank yet
        "appointmentscheduled": "pending",
        "qualifiedtobuy": "pending",
        "presentationscheduled": "pending",
        "decisionmakerboughtin": "pending",
        "contractsent": "pending",
    },
}


def canonical_status(source: str, raw_status: str) -> str:
    return STATUS_MAP.get(source, {}).get((raw_status or "").lower(), "unknown")
