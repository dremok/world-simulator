"""Worker entrypoint: run every enabled ingester once. Railway cron calls this."""

from ingest import usgs
from ingest.db import connect


def main() -> None:
    with connect() as conn:
        usgs.run(conn)


if __name__ == "__main__":
    main()
