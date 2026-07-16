"""CLI entry point for the sync pipeline.

    python -m scripts.run_sync                 # incremental sync, all sources
    python -m scripts.run_sync --source stripe # just one source
    python -m scripts.run_sync --full          # drop cursors, force a backfill
"""

import argparse
import json
import logging

from app import db, sync


def main():
    parser = argparse.ArgumentParser(description="Run the sync pipeline")
    parser.add_argument("--source", choices=sorted(sync.SOURCES))
    parser.add_argument("--full", action="store_true",
                        help="reset stored cursors first to force a full backfill")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.full:
        with db.connect() as conn:
            for name in sync.SOURCES:
                if not args.source or name == args.source:
                    sync.reset_cursor(conn, name)
            conn.commit()

    print(json.dumps(sync.run(only=args.source), indent=2, default=str))


if __name__ == "__main__":
    main()
