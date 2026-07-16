import os

import pytest

from app import db


@pytest.fixture
def conn():
    """A connection whose work is always rolled back, so DB tests can run
    against the real Supabase instance without leaving anything behind."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    with db.connect() as c:
        yield c
        c.rollback()
