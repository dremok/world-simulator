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


@app.get("/storylines")
def storylines_list(status: str = Query(default="active"), limit: int = Query(default=30, ge=1, le=200)) -> list:
    sql = """
        SELECT s.id, s.title, s.summary, s.status, s.cluster_key, s.heat,
               s.started_at, s.last_activity_at, s.closed_kind, s.closed_summary,
               count(se.event_id) AS event_count
        FROM storylines s
        LEFT JOIN storyline_events se ON se.storyline_id = s.id
        WHERE s.status = %s
        GROUP BY s.id
        ORDER BY s.heat DESC, s.last_activity_at DESC
        LIMIT %s
    """
    with _connect() as conn:
        rows = conn.execute(sql, (status, limit)).fetchall()
    return [
        {
            "id": id_,
            "title": title,
            "summary": summary,
            "status": status_,
            "country_iso": (cluster_key or ":").split(":")[0] or None,
            "verb_class": (cluster_key or ":").split(":")[1] or None,
            "heat": round(heat, 2),
            "started_at": started_at.isoformat(),
            "last_activity_at": last_activity_at.isoformat(),
            "closed_kind": closed_kind,
            "closed_summary": closed_summary,
            "event_count": event_count,
        }
        for id_, title, summary, status_, cluster_key, heat, started_at,
            last_activity_at, closed_kind, closed_summary, event_count in rows
    ]


@app.get("/storylines/{storyline_id}")
def storyline_detail(storyline_id: int) -> dict:
    with _connect() as conn:
        s = conn.execute(
            "SELECT id, title, summary, status, cluster_key, heat, started_at, last_activity_at, closed_kind, closed_summary FROM storylines WHERE id = %s",
            (storyline_id,),
        ).fetchone()
        if not s:
            return {"error": "not found"}
        events = conn.execute(
            """
            SELECT e.id, e.event_type, e.summary, e.severity, e.importance,
                   e.occurred_at, e.payload->>'url' AS url
            FROM storyline_events se JOIN events e ON e.id = se.event_id
            WHERE se.storyline_id = %s
            ORDER BY e.occurred_at DESC
            LIMIT 200
            """,
            (storyline_id,),
        ).fetchall()
    return {
        "id": s[0], "title": s[1], "summary": s[2], "status": s[3],
        "cluster_key": s[4], "heat": round(s[5], 2),
        "started_at": s[6].isoformat(), "last_activity_at": s[7].isoformat(),
        "closed_kind": s[8], "closed_summary": s[9],
        "event_ids": [e[0] for e in events],
        "events": [
            {
                "id": id_, "event_type": event_type, "summary": summary,
                "severity": severity, "importance": importance,
                "occurred_at": occurred_at.isoformat(), "url": url,
            }
            for id_, event_type, summary, severity, importance, occurred_at, url in events
        ],
    }


@app.get("/layers/state.json")
def state_layer() -> dict:
    """Latest state per country plus per-country anomaly vs its own history."""
    sql = """
        WITH latest AS (
            SELECT DISTINCT ON (country_iso) country_iso, ts, tension, econ_mood, attention
            FROM country_state ORDER BY country_iso, ts DESC
        ),
        hist AS (
            SELECT country_iso,
                   avg(tension) AS t_mean, stddev_samp(tension) AS t_std,
                   count(*) AS n
            FROM country_state
            WHERE ts > now() - interval '90 days'
            GROUP BY country_iso
        )
        SELECT l.country_iso, l.tension, l.econ_mood, l.attention,
               CASE WHEN h.n >= 12 AND h.t_std > 0.01
                    THEN (l.tension - h.t_mean) / h.t_std END AS tension_anomaly
        FROM latest l JOIN hist h USING (country_iso)
    """
    with _connect() as conn:
        rows = conn.execute(sql).fetchall()
    return {
        iso: {
            "tension": round(tension, 3),
            "econ_mood": round(econ_mood, 3),
            "attention": round(attention, 3),
            "tension_anomaly": round(anom, 2) if anom is not None else None,
        }
        for iso, tension, econ_mood, attention, anom in rows
    }


VERB_CLASS_SQL = """
    CASE
      WHEN event_type IN ('fight','assault','coerce','threaten','force_posture','mass_violence','reduce_relations') THEN 'conflict'
      WHEN event_type IN ('diplomatic_cooperation','material_cooperation','provide_aid','intent_to_cooperate','yield','consult','appeal') THEN 'cooperation'
      WHEN event_type = 'protest' THEN 'protest'
      ELSE 'other'
    END
"""


@app.get("/relation")
def relation(
    a: str = Query(..., min_length=3, max_length=3),
    b: str = Query(..., min_length=3, max_length=3),
    hours: int = Query(default=168, ge=1, le=24 * 90),
) -> dict:
    """Everything between two CAMEO country codes (alpha-3), both directions."""
    a, b = a.upper(), b.upper()
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, event_type, {VERB_CLASS_SQL} AS verb_class, actor1, actor2,
                   actor1_cc, actor2_cc, lat, lon, goldstein, tone, importance,
                   occurred_at, summary, payload->>'url' AS url
            FROM events
            WHERE occurred_at > now() - make_interval(hours => %s)
              AND ((actor1_cc = %s AND actor2_cc = %s) OR (actor1_cc = %s AND actor2_cc = %s))
            ORDER BY importance DESC
            LIMIT 500
            """,
            (hours, a, b, b, a),
        ).fetchall()
    verb_mix: dict[str, int] = {}
    goldsteins = []
    features = []
    for (id_, event_type, verb_class, actor1, actor2, a1cc, a2cc, lat, lon,
         goldstein, tone, importance, occurred_at, summary, url) in rows:
        verb_mix[verb_class] = verb_mix.get(verb_class, 0) + 1
        if goldstein is not None:
            goldsteins.append(goldstein)
        if lat is not None and lon is not None:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "id": id_, "event_type": event_type, "verb_class": verb_class,
                    "actor1": actor1, "actor2": actor2, "importance": importance,
                    "occurred_at": occurred_at.isoformat(), "summary": summary, "url": url,
                },
            })
    return {
        "a": a, "b": b, "hours": hours, "count": len(rows),
        "verb_mix": verb_mix,
        "avg_goldstein": round(sum(goldsteins) / len(goldsteins), 2) if goldsteins else None,
        "events": {"type": "FeatureCollection", "features": features},
    }


@app.get("/diff")
def world_diff(since: str = Query(...)) -> dict:
    """What changed: storylines opened or closed since the given ISO timestamp."""
    with _connect() as conn:
        opened = conn.execute(
            "SELECT id, title, cluster_key, heat FROM storylines WHERE started_at > %s ORDER BY heat DESC",
            (since,),
        ).fetchall()
        closed = conn.execute(
            "SELECT id, title, cluster_key, closed_kind FROM storylines WHERE status = 'closed' AND updated_at > %s",
            (since,),
        ).fetchall()
        new_events = conn.execute(
            "SELECT count(*) FROM events WHERE created_at > %s", (since,)
        ).fetchone()[0]
    return {
        "since": since,
        "new_events": new_events,
        "opened": [{"id": i, "title": t, "cluster_key": k, "heat": round(h, 2)} for i, t, k, h in opened],
        "closed": [{"id": i, "title": t, "cluster_key": k, "closed_kind": ck} for i, t, k, ck in closed],
    }


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
