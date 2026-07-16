class SourceError(Exception):
    """A source is misconfigured, unreachable, or returned garbage."""


class StaleCursor(SourceError):
    """The source rejected our incremental cursor (expired sync token,
    malformed value, 410, ...). Recovery is a full backfill, never a crash
    and never silently skipping the window."""
