"""Heuristic storyline clustering. Free tier: no LLM, no embeddings.

A storyline v1 is "sustained activity of one verb class in one country":
cluster_key = '{country_iso}:{verb_class}'. Each worker run attaches new
qualifying events to the active storyline for their key (or opens one),
recomputes heat, and walks the lifecycle:

    active --(7 days quiet)--> stale --(14 days quiet)--> closed (kind=quiet)

'resolved' closures and real titles/summaries come from narrator sessions
(the /enrich skill); this module only does arithmetic. Everything here is
re-derivable from events.
"""

from datetime import datetime, timedelta, timezone

import psycopg

VERB_CLASS = {
    "fight": "conflict", "assault": "conflict", "coerce": "conflict",
    "threaten": "conflict", "force_posture": "conflict",
    "mass_violence": "conflict", "reduce_relations": "conflict",
    "protest": "protest",
    "diplomatic_cooperation": "cooperation", "material_cooperation": "cooperation",
    "provide_aid": "cooperation", "intent_to_cooperate": "cooperation",
    "yield": "cooperation", "consult": "cooperation", "appeal": "cooperation",
}

MIN_STORYLINE_IMPORTANCE = 0.35   # events below this stay on the map but off storylines
STALE_AFTER = timedelta(days=7)
CLOSE_AFTER = timedelta(days=14)
HEAT_WINDOW_HOURS = 72


def _attach_new_events(conn: psycopg.Connection) -> int:
    """Attach unassigned qualifying events to storylines, creating as needed."""
    rows = conn.execute(
        """
        SELECT e.id, e.event_type, e.country_iso, e.occurred_at
        FROM events e
        LEFT JOIN storyline_events se ON se.event_id = e.id
        WHERE se.event_id IS NULL
          AND e.country_iso IS NOT NULL
          AND e.importance >= %s
        ORDER BY e.occurred_at
        """,
        (MIN_STORYLINE_IMPORTANCE,),
    ).fetchall()

    attached = 0
    for event_id, event_type, country_iso, occurred_at in rows:
        verb_class = VERB_CLASS.get(event_type)
        if verb_class is None:
            continue
        key = f"{country_iso}:{verb_class}"
        storyline = conn.execute(
            """
            SELECT id FROM storylines
            WHERE cluster_key = %s AND status IN ('active', 'stale')
            """,
            (key,),
        ).fetchone()
        if storyline:
            storyline_id = storyline[0]
            conn.execute(
                """
                UPDATE storylines
                SET last_activity_at = GREATEST(last_activity_at, %s),
                    status = 'active', updated_at = now()
                WHERE id = %s
                """,
                (occurred_at, storyline_id),
            )
        else:
            storyline_id = conn.execute(
                """
                INSERT INTO storylines (title, cluster_key, status, started_at, last_activity_at)
                VALUES (%s, %s, 'active', %s, %s)
                RETURNING id
                """,
                (f"{verb_class} · {country_iso}", key, occurred_at, occurred_at),
            ).fetchone()[0]
        conn.execute(
            "INSERT INTO storyline_events (storyline_id, event_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (storyline_id, event_id),
        )
        attached += 1
    return attached


def _recompute_heat(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        UPDATE storylines s
        SET heat = COALESCE(sub.h, 0)
        FROM (
            SELECT se.storyline_id, sum(e.importance) AS h
            FROM storyline_events se
            JOIN events e ON e.id = se.event_id
            WHERE e.occurred_at > now() - make_interval(hours => %s)
            GROUP BY se.storyline_id
        ) sub
        WHERE s.id = sub.storyline_id AND s.status IN ('active', 'stale')
        """,
        (HEAT_WINDOW_HOURS,),
    )
    conn.execute(
        """
        UPDATE storylines SET heat = 0
        WHERE status IN ('active', 'stale')
          AND id NOT IN (
            SELECT se.storyline_id FROM storyline_events se
            JOIN events e ON e.id = se.event_id
            WHERE e.occurred_at > now() - make_interval(hours => %s)
          )
        """,
        (HEAT_WINDOW_HOURS,),
    )


def _walk_lifecycle(conn: psycopg.Connection) -> tuple[int, int]:
    now = datetime.now(tz=timezone.utc)
    stale = conn.execute(
        """
        UPDATE storylines SET status = 'stale', updated_at = now()
        WHERE status = 'active' AND last_activity_at < %s
        RETURNING id
        """,
        (now - STALE_AFTER,),
    ).fetchall()
    closed = conn.execute(
        """
        UPDATE storylines
        SET status = 'closed', closed_kind = 'quiet', updated_at = now()
        WHERE status = 'stale' AND last_activity_at < %s
        RETURNING id
        """,
        (now - CLOSE_AFTER,),
    ).fetchall()
    return len(stale), len(closed)


def run(conn: psycopg.Connection) -> None:
    attached = _attach_new_events(conn)
    _recompute_heat(conn)
    went_stale, went_quiet = _walk_lifecycle(conn)
    conn.commit()
    n_active = conn.execute(
        "SELECT count(*) FROM storylines WHERE status = 'active'"
    ).fetchone()[0]
    print(
        f"storylines: {attached} events attached, {n_active} active, "
        f"{went_stale} went stale, {went_quiet} closed quiet"
    )
