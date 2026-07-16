import pathlib

import psycopg
from psycopg.rows import dict_row

from . import config

SCHEMA_FILE = pathlib.Path(__file__).resolve().parent.parent / "schema.sql"


def connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return psycopg.connect(config.DATABASE_URL, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_FILE.read_text())
    conn.commit()
