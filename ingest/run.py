"""Worker entrypoint: run every enabled ingester once. Railway cron calls this."""

import os

from extract import storylines
from ingest import gdelt, rss, usgs
from ingest.db import connect


def _enabled(var: str) -> bool:
    return os.environ.get(var, "true").lower() in ("1", "true", "yes")


def main() -> None:
    with connect() as conn:
        usgs.run(conn)
        if _enabled("GDELT_ENABLED"):
            gdelt.run(conn)
        if _enabled("RSS_ENABLED"):
            rss.run(conn)
        storylines.run(conn)


if __name__ == "__main__":
    main()
