"""Enrichment plumbing: select, fetch, and apply. The LLM is the session.

The LLM itself is deliberately NOT called here. A Claude Code session (the
/enrich skill) is the driver. Standard ad-hoc flow, three commands:

    python -m extract.enrich fetch [limit]       # pending events + extracted
                                                 #   article text, JSON to stdout
    (session writes summaries from that JSON)
    python -m extract.enrich apply < results.json

`fetch` downloads each pending event's article (grouped by URL) and extracts
main text with trafilatura. Dead/blocked URLs are marked fetch_failed in the
event payload and excluded from future runs, so the queue always drains.
`pending` remains for inspection without fetching; `narrate-pending` /
`narrate-apply` are the storyline pass.
"""

import json
import os
import sys

import httpx
import psycopg
import trafilatura
from dotenv import load_dotenv

PENDING_SQL = """
    SELECT id, event_type, actor1, actor2, country_iso, admin1,
           tone, goldstein, importance, occurred_at, payload
    FROM events
    WHERE enriched_at IS NULL
      AND importance >= %s
      AND COALESCE(payload->>'fetch_failed', '') != 'true'
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
    """Accepts items with either `id` (int) or `event_ids` (list) from fetch."""
    raw = json.load(sys.stdin)
    items, errors = [], []
    for item in raw:
        ids = item.get("event_ids") or ([item["id"]] if isinstance(item.get("id"), int) else [])
        if not ids or not item.get("summary"):
            errors.append(f"bad item: {item}")
            continue
        sev = item.get("severity")
        if not isinstance(sev, int) or not 1 <= sev <= 5:
            errors.append(f"bad severity on {ids}: {sev!r}")
            continue
        items.extend({"id": i, "summary": item["summary"], "severity": sev} for i in ids)
    if errors:
        sys.exit("\n".join(errors))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(APPLY_SQL, items)
        conn.commit()
    print(f"applied {len(items)} enrichments")


def fetch(limit: int) -> None:
    """Pending events with extracted article text, grouped by URL."""
    threshold = float(os.environ.get("IMPORTANCE_THRESHOLD", "0.35"))
    with _connect() as conn:
        rows = conn.execute(PENDING_SQL, (threshold, limit)).fetchall()
        by_url: dict[str, list] = {}
        meta: dict[str, dict] = {}
        for (id_, event_type, actor1, actor2, country_iso, admin1,
             tone, goldstein, importance, occurred_at, payload) in rows:
            url = (payload or {}).get("url")
            if not url:
                continue
            by_url.setdefault(url, []).append(id_)
            meta[url] = {"event_type": event_type, "actor1": actor1, "actor2": actor2,
                         "country_iso": country_iso, "importance": importance}

        out, failed = [], []
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (world-simulator enrich)"}) as client:
            for url, ids in by_url.items():
                text = None
                try:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        text = trafilatura.extract(resp.text, include_comments=False)
                except httpx.HTTPError:
                    pass
                if text:
                    out.append({"event_ids": ids, "url": url, **meta[url],
                                "article_excerpt": text[:1800]})
                else:
                    failed.extend(ids)

        if failed:
            conn.execute(
                """
                UPDATE events SET payload = COALESCE(payload, '{}'::jsonb) || '{"fetch_failed": "true"}'::jsonb
                WHERE id = ANY(%s)
                """,
                (failed,),
            )
            conn.commit()

    json.dump(out, sys.stdout, indent=1)
    print(f"\n{len(out)} articles fetched for {sum(len(o['event_ids']) for o in out)} events; "
          f"{len(failed)} events marked fetch_failed and skipped from future runs", file=sys.stderr)


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
    "fetch": lambda: fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 60),
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
