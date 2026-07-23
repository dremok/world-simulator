"""FastAPI app: GeoJSON layers + static frontend (web/dist) on one URL."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

load_dotenv()

app = FastAPI(title="world-simulator")

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


def _connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"])


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/layers/events.geojson")
def events_geojson(
    hours: int = Query(default=168, ge=1, le=24 * 90),
    min_importance: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=2000, ge=1, le=10000),
) -> dict:
    sql = """
        SELECT id, external_id, event_type, lat, lon, importance,
               occurred_at, payload
        FROM events
        WHERE occurred_at > now() - make_interval(hours => %s)
          AND importance >= %s
          AND lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY importance DESC
        LIMIT %s
    """
    with _connect() as conn:
        rows = conn.execute(sql, (hours, min_importance, limit)).fetchall()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": id_,
                "external_id": external_id,
                "event_type": event_type,
                "importance": importance,
                "occurred_at": occurred_at.isoformat(),
                **(payload or {}),
            },
        }
        for id_, external_id, event_type, lat, lon, importance, occurred_at, payload in rows
    ]
    return {"type": "FeatureCollection", "features": features}


# Built frontend, mounted last so API routes win. Missing locally until `npm run build`.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
