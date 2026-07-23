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


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("pending", "apply"):
        sys.exit(__doc__)
    if sys.argv[1] == "pending":
        pending(int(sys.argv[2]) if len(sys.argv) > 2 else 50)
    else:
        apply()


if __name__ == "__main__":
    main()
