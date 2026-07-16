"""Apply schema.sql. Safe to run repeatedly (everything is IF NOT EXISTS)."""

from app import db


def main():
    with db.connect() as conn:
        db.init_schema(conn)
    print("schema applied")


if __name__ == "__main__":
    main()
