"""Worker entrypoint: run every enabled ingester once. Railway cron calls this."""

import os

from extract import entities, storylines
from ingest import gdelt, rss
from ingest.db import connect
from sim import state


def _enabled(var: str) -> bool:
    return os.environ.get(var, "true").lower() in ("1", "true", "yes")


def main() -> None:
    with connect() as conn:
        if _enabled("GDELT_ENABLED"):
            gdelt.run(conn)
        if _enabled("RSS_ENABLED"):
            rss.run(conn)
        storylines.run(conn)
        entities.run(conn)
        state.run(conn)


if __name__ == "__main__":
    main()
