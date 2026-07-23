"""USGS earthquake ingest.

Fetches the past-week GeoJSON summary feed, upserts quakes above a minimum
magnitude into events, and advances the 'usgs' watermark to the newest
`updated` timestamp seen. Idempotent: re-running upserts the same rows.
"""

from datetime import datetime, timezone

import httpx
import psycopg

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson"
MIN_MAGNITUDE = 2.5

UPSERT_SQL = """
INSERT INTO events (external_id, event_type, lat, lon, importance, occurred_at, payload)
VALUES (%(external_id)s, 'earthquake', %(lat)s, %(lon)s, %(importance)s, %(occurred_at)s, %(payload)s)
ON CONFLICT (external_id) DO UPDATE SET
    lat = EXCLUDED.lat,
    lon = EXCLUDED.lon,
    importance = EXCLUDED.importance,
    occurred_at = EXCLUDED.occurred_at,
    payload = EXCLUDED.payload
"""


def _ts(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def importance_for(magnitude: float) -> float:
    """Map magnitude to the 0-1 importance scale; mag 8+ saturates at 1."""
    return max(0.0, min(1.0, magnitude / 8.0))


def run(conn: psycopg.Connection) -> None:
    row = conn.execute(
        "SELECT watermark_ts FROM ingest_watermarks WHERE source = 'usgs'"
    ).fetchone()
    watermark = row[0] if row else datetime.fromtimestamp(0, tz=timezone.utc)

    resp = httpx.get(FEED_URL, timeout=30)
    resp.raise_for_status()
    features = resp.json()["features"]

    upserted = 0
    max_updated = watermark
    with conn.cursor() as cur:
        for f in features:
            props = f["properties"]
            mag = props.get("mag")
            if mag is None or mag < MIN_MAGNITUDE:
                continue
            updated = _ts(props["updated"])
            if updated <= watermark:
                continue
            lon, lat = f["geometry"]["coordinates"][:2]
            cur.execute(
                UPSERT_SQL,
                {
                    "external_id": f"usgs:{f['id']}",
                    "lat": lat,
                    "lon": lon,
                    "importance": importance_for(mag),
                    "occurred_at": _ts(props["time"]),
                    "payload": psycopg.types.json.Jsonb(
                        {
                            "magnitude": mag,
                            "place": props.get("place"),
                            "depth_km": f["geometry"]["coordinates"][2]
                            if len(f["geometry"]["coordinates"]) > 2
                            else None,
                            "url": props.get("url"),
                            "alert": props.get("alert"),
                            "tsunami": props.get("tsunami"),
                        }
                    ),
                },
            )
            upserted += 1
            max_updated = max(max_updated, updated)

        cur.execute(
            """
            INSERT INTO ingest_watermarks (source, watermark_ts, updated_at)
            VALUES ('usgs', %s, now())
            ON CONFLICT (source) DO UPDATE
                SET watermark_ts = EXCLUDED.watermark_ts, updated_at = now()
            """,
            (max_updated,),
        )
    conn.commit()
    print(f"usgs: {len(features)} in feed, {upserted} upserted, watermark {max_updated.isoformat()}")
