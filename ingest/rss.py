"""RSS article ingest.

Syncs config/feeds.yaml into sources, then polls each feed and inserts new
articles. Idempotent two ways: URL is unique, and a normalized-title check
against the last 3 days catches the same story re-published under a new URL.
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import psycopg
import yaml

FEEDS_PATH = Path(__file__).resolve().parent.parent / "config" / "feeds.yaml"


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()


def _published_at(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _sync_sources(conn: psycopg.Connection) -> dict[str, int]:
    feeds = yaml.safe_load(FEEDS_PATH.read_text())["feeds"]
    ids = {}
    for f in feeds:
        row = conn.execute(
            """
            INSERT INTO sources (name, kind, url, country, trust_weight)
            VALUES (%(name)s, 'rss', %(url)s, %(country)s, %(trust_weight)s)
            ON CONFLICT (name) DO UPDATE
                SET url = EXCLUDED.url,
                    country = EXCLUDED.country,
                    trust_weight = EXCLUDED.trust_weight
            RETURNING id
            """,
            f,
        ).fetchone()
        ids[f["url"]] = row[0]
    return ids


def run(conn: psycopg.Connection) -> None:
    source_ids = _sync_sources(conn)
    inserted = skipped_dupe_title = 0

    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "world-simulator/0.1"}) as client:
        for feed_url, source_id in source_ids.items():
            try:
                parsed = feedparser.parse(client.get(feed_url).content)
            except httpx.HTTPError as exc:
                print(f"rss: {feed_url} failed: {exc}")
                continue
            for entry in parsed.entries:
                url = entry.get("link")
                title = (entry.get("title") or "").strip()
                if not url or not title:
                    continue
                dupe = conn.execute(
                    """
                    SELECT 1 FROM articles
                    WHERE fetched_at > now() - interval '3 days'
                      AND lower(regexp_replace(title, '[^a-zA-Z0-9 ]', '', 'g')) = %s
                    LIMIT 1
                    """,
                    (_normalize_title(title),),
                ).fetchone()
                if dupe:
                    skipped_dupe_title += 1
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO articles (source_id, url, title, published_at, raw_text)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO NOTHING
                    """,
                    (source_id, url, title, _published_at(entry), entry.get("summary")),
                )
                inserted += cur.rowcount

    conn.commit()
    print(f"rss: {inserted} new articles, {skipped_dupe_title} title dupes skipped")
