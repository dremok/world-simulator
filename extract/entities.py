"""Entity extraction from event actors. Free tier, re-derivable.

GDELT actor names are noisy ("THE US", "POLICE") but consistent enough to
aggregate. Each run: events with no mentions yet -> upsert entities, record
mentions, and accumulate pair relations weighted by importance. The
entity_relations table is the graph behind relation mode and future dossiers.
"""

import psycopg

from extract.storylines import VERB_CLASS

MIN_NAME_LEN = 3
GENERIC = {
    "POLICE", "GOVERNMENT", "PRESIDENT", "MILITARY", "COMPANY", "BUSINESS",
    "SCHOOL", "MEDIA", "CIVILIAN", "PROTESTER", "STUDENT", "COURT", "SENATE",
    "CONGRESS", "MINISTRY", "HOSPITAL", "PRISON", "BANK", "AIRLINE", "JOURNALIST", "COMMUNITY", "CITIZEN", "OFFICIAL", "LEADER", "MINISTER",
}


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip().upper()
    if len(name) < MIN_NAME_LEN or name in GENERIC:
        return None
    return name.title()


def run(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        SELECT e.id, e.event_type, e.actor1, e.actor2, e.importance
        FROM events e
        WHERE NOT EXISTS (SELECT 1 FROM entity_mentions m WHERE m.event_id = e.id)
          AND (e.actor1 IS NOT NULL OR e.actor2 IS NOT NULL)
        ORDER BY e.id
        LIMIT 5000
        """
    ).fetchall()

    ids: dict[str, int] = {}

    def entity_id(name: str) -> int:
        if name not in ids:
            ids[name] = conn.execute(
                """
                INSERT INTO entities (name, kind) VALUES (%s, 'actor')
                ON CONFLICT (name, kind) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (name,),
            ).fetchone()[0]
        return ids[name]

    mentions = relations = 0
    for event_id, event_type, actor1, actor2, importance in rows:
        a1, a2 = _clean(actor1), _clean(actor2)
        for name, role in ((a1, "actor1"), (a2, "actor2")):
            if not name:
                continue
            conn.execute(
                "INSERT INTO entity_mentions (entity_id, event_id, role) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (entity_id(name), event_id, role),
            )
            mentions += 1
        if a1 and a2 and a1 != a2:
            ea, eb = sorted((entity_id(a1), entity_id(a2)))
            conn.execute(
                """
                INSERT INTO entity_relations (a_id, b_id, relation, weight, last_seen_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (a_id, b_id, relation) DO UPDATE
                    SET weight = entity_relations.weight + EXCLUDED.weight,
                        last_seen_at = now()
                """,
                (ea, eb, VERB_CLASS.get(event_type, "other"), importance),
            )
            relations += 1
    conn.commit()
    print(f"entities: {len(rows)} events processed, {mentions} mentions, {relations} relation updates")
