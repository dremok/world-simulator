"""Enrichment plumbing: select events that need LLM enrichment, apply results.

The LLM itself is deliberately NOT called here. A Claude Code session (the
/enrich skill) is the driver: it runs `pending`, writes the summaries, and
pipes them into `apply`. Keeping the boundary here means an API-based worker
could drive the same module later without touching this file.

Usage:
    python -m extract.enrich pending [limit]     # JSON array to stdout
    python -m extract.enrich apply < results.json
"""

import json
import os
import sys

import psycopg
from dotenv import load_dotenv

PENDING_SQL = """
    SELECT id, event_type, actor1, actor2, country_iso, admin1,
           tone, goldstein, importance, occurred_at, payload
    FROM events
    WHERE enriched_at IS NULL
      AND importance >= %s
      AND event_type != 'earthquake'  -- quakes are self-describing (magnitude, place)
    ORDER BY importance DESC
    LIMIT %s
"""

APPLY_SQL = """
    UPDATE events
    SET summary = %(summary)s,
        severity = %(severity)s,
        enriched_at = now()
    WHERE id = %(id)s
"""


def _connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def pending(limit: int) -> None:
    threshold = float(os.environ.get("IMPORTANCE_THRESHOLD", "0.6"))
    with _connect() as conn:
        rows = conn.execute(PENDING_SQL, (threshold, limit)).fetchall()
    out = [
        {
            "id": id_,
            "event_type": event_type,
            "actor1": actor1,
            "actor2": actor2,
            "country_iso": country_iso,
            "admin1": admin1,
            "tone": tone,
            "goldstein": goldstein,
            "importance": importance,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
        }
        for id_, event_type, actor1, actor2, country_iso, admin1,
            tone, goldstein, importance, occurred_at, payload in rows
    ]
    json.dump(out, sys.stdout, indent=1)
    print(file=sys.stderr)
    print(f"{len(out)} events pending enrichment", file=sys.stderr)


def apply() -> None:
    items = json.load(sys.stdin)
    errors = []
    for item in items:
        if not isinstance(item.get("id"), int) or not item.get("summary"):
            errors.append(f"bad item: {item}")
            continue
        sev = item.get("severity")
        if not isinstance(sev, int) or not 1 <= sev <= 5:
            errors.append(f"bad severity on id {item['id']}: {sev!r}")
    if errors:
        sys.exit("\n".join(errors))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(APPLY_SQL, items)
        conn.commit()
    print(f"applied {len(items)} enrichments")


NARRATE_PENDING_SQL = """
    SELECT s.id, s.title, s.summary, s.status, s.cluster_key, s.heat,
           s.started_at, s.last_activity_at,
           (SELECT json_agg(json_build_object(
                'event_type', e.event_type, 'actor1', e.actor1, 'actor2', e.actor2,
                'summary', e.summary, 'url', e.payload->>'url',
                'occurred_at', e.occurred_at, 'importance', e.importance)
                ORDER BY e.importance DESC)
            FROM (SELECT e.* FROM storyline_events se JOIN events e ON e.id = se.event_id
                  WHERE se.storyline_id = s.id
                  ORDER BY e.importance DESC LIMIT 12) e) AS top_events
    FROM storylines s
    WHERE (s.narrated_at IS NULL OR s.last_activity_at > s.narrated_at
           OR (s.status = 'closed' AND s.closed_summary IS NULL))
      AND s.heat > 0.5
    ORDER BY s.heat DESC
    LIMIT %s
"""

NARRATE_APPLY_SQL = """
    UPDATE storylines
    SET title = COALESCE(%(title)s, title),
        summary = COALESCE(%(summary)s, summary),
        closed_kind = COALESCE(%(closed_kind)s, closed_kind),
        closed_summary = COALESCE(%(closed_summary)s, closed_summary),
        narrated_at = now(),
        updated_at = now()
    WHERE id = %(id)s
"""


def narrate_pending(limit: int) -> None:
    with _connect() as conn:
        rows = conn.execute(NARRATE_PENDING_SQL, (limit,)).fetchall()
    out = [
        {
            "id": id_, "title": title, "summary": summary, "status": status,
            "cluster_key": cluster_key, "heat": heat,
            "started_at": started_at.isoformat(),
            "last_activity_at": last_activity_at.isoformat(),
            "top_events": top_events,
        }
        for id_, title, summary, status, cluster_key, heat,
            started_at, last_activity_at, top_events in rows
    ]
    json.dump(out, sys.stdout, indent=1, default=str)
    print(f"\n{len(out)} storylines pending narration", file=sys.stderr)


def narrate_apply() -> None:
    items = json.load(sys.stdin)
    for item in items:
        if not isinstance(item.get("id"), int):
            sys.exit(f"bad item: {item}")
        if item.get("closed_kind") not in (None, "resolved", "quiet"):
            sys.exit(f"bad closed_kind on id {item['id']}")
        item.setdefault("title", None)
        item.setdefault("summary", None)
        item.setdefault("closed_kind", None)
        item.setdefault("closed_summary", None)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(NARRATE_APPLY_SQL, items)
        conn.commit()
    print(f"applied {len(items)} narrations")


COMMANDS = {
    "pending": lambda: pending(int(sys.argv[2]) if len(sys.argv) > 2 else 50),
    "apply": apply,
    "narrate-pending": lambda: narrate_pending(int(sys.argv[2]) if len(sys.argv) > 2 else 20),
    "narrate-apply": narrate_apply,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()


if __name__ == "__main__":
    main()
