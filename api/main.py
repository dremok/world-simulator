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
               occurred_at, payload, summary, severity
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
                "summary": summary,
                "severity": severity,
                **(payload or {}),
            },
        }
        for id_, external_id, event_type, lat, lon, importance, occurred_at, payload, summary, severity in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@app.get("/layers/country_stats.json")
def country_stats(hours: int = Query(default=24, ge=1, le=24 * 90)) -> dict:
    sql = """
        SELECT country_iso,
               count(*) AS event_count,
               avg(tone) AS avg_tone,
               max(importance) AS max_importance
        FROM events
        WHERE occurred_at > now() - make_interval(hours => %s)
          AND country_iso IS NOT NULL
        GROUP BY country_iso
    """
    with _connect() as conn:
        rows = conn.execute(sql, (hours,)).fetchall()
    return {
        iso: {
            "count": count,
            "avg_tone": round(avg_tone, 2) if avg_tone is not None else None,
            "max_importance": max_importance,
        }
        for iso, count, avg_tone, max_importance in rows
    }


# Built frontend, mounted last so API routes win. Missing locally until `npm run build`.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
