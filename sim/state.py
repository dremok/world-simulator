"""Country state vectors: the simulation tier.

Every worker run appends one snapshot per country with recent activity:

    state = prev * exp(-dt / half_life) + sum(impact(event))

Impacts come from verb class and importance; tone feeds econ_mood.
Baselines are NOT hardcoded: the anomaly view derives each country's
baseline from its own snapshot history (mean/std), so France's protest
noise and Singapore's quiet are learned, not asserted. Snapshots are
append-only; the table is the time machine.
"""

from datetime import datetime, timedelta, timezone
from math import exp

import psycopg

from extract.storylines import VERB_CLASS

HALF_LIFE_H = {"tension": 36.0, "econ_mood": 72.0, "attention": 12.0}

# importance-weighted impact per verb class
TENSION_W = {"conflict": 1.0, "protest": 0.45, "cooperation": -0.25}
MAX_SNAPSHOT_GAP_H = 6.0


def run(conn: psycopg.Connection) -> None:
    now = datetime.now(tz=timezone.utc)
    last_row = conn.execute("SELECT max(ts) FROM country_state").fetchone()
    last_ts = last_row[0] if last_row and last_row[0] else now - timedelta(hours=1)
    dt_h = min((now - last_ts).total_seconds() / 3600.0, MAX_SNAPSHOT_GAP_H)
    if dt_h < 0.05:
        print("state: skipped (snapshot too recent)")
        return

    prev = {
        iso: {"tension": t, "econ_mood": e, "attention": a}
        for iso, t, e, a in conn.execute(
            """
            SELECT DISTINCT ON (country_iso) country_iso, tension, econ_mood, attention
            FROM country_state ORDER BY country_iso, ts DESC
            """
        )
    }

    impacts: dict[str, dict[str, float]] = {}
    for iso, event_type, importance, tone in conn.execute(
        """
        SELECT country_iso, event_type, importance, tone
        FROM events
        WHERE created_at > %s AND country_iso IS NOT NULL
        """,
        (last_ts,),
    ):
        verb_class = VERB_CLASS.get(event_type)
        d = impacts.setdefault(iso, {"tension": 0.0, "econ_mood": 0.0, "attention": 0.0})
        d["attention"] += importance
        d["tension"] += importance * TENSION_W.get(verb_class, 0.0)
        if tone is not None:
            d["econ_mood"] += importance * (tone / 10.0)

    countries = set(prev) | set(impacts)
    rows = []
    for iso in countries:
        p = prev.get(iso, {"tension": 0.0, "econ_mood": 0.0, "attention": 0.0})
        i = impacts.get(iso, {"tension": 0.0, "econ_mood": 0.0, "attention": 0.0})
        state = {
            dim: p[dim] * exp(-dt_h / HALF_LIFE_H[dim] * 0.693) + i[dim]
            for dim in ("tension", "econ_mood", "attention")
        }
        if all(abs(v) < 0.01 for v in state.values()):
            continue  # fully decayed and quiet: stop snapshotting this country
        rows.append((iso, now, state["tension"], state["econ_mood"], state["attention"]))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO country_state (country_iso, ts, tension, stability, disaster, econ_mood, attention)
            VALUES (%s, %s, %s, 0, 0, %s, %s)
            ON CONFLICT (country_iso, ts) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    print(f"state: snapshot for {len(rows)} countries, dt={dt_h:.2f}h")
