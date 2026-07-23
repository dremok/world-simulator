"""Apply db/migrations/*.sql in filename order, tracking applied ones in schema_migrations."""

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"


def main() -> None:
    load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL is not set")

    with psycopg.connect(dsn) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  name TEXT PRIMARY KEY,"
            "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
            ")"
        )
        applied = {
            row[0] for row in conn.execute("SELECT name FROM schema_migrations")
        }
        pending = [
            p for p in sorted(MIGRATIONS_DIR.glob("*.sql")) if p.name not in applied
        ]
        if not pending:
            print("Nothing to migrate.")
            return
        for path in pending:
            print(f"Applying {path.name} ...")
            with conn.transaction():
                conn.execute(path.read_text())
                conn.execute(
                    "INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,)
                )
        print(f"Applied {len(pending)} migration(s).")


if __name__ == "__main__":
    main()
