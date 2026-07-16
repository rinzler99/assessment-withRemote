from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Record:
    """The one shape every source gets normalized into."""

    source: str
    source_id: str
    kind: str  # contact | deal | payment | event
    title: str = ""
    status: str = ""
    amount_cents: int | None = None
    currency: str | None = None
    occurred_at: datetime | None = None
    raw: dict = field(default_factory=dict)
