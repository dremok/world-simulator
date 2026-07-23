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


ALIASES = {
    "THE US": "UNITED STATES", "USA": "UNITED STATES", "AMERICA": "UNITED STATES",
    "AMERICAN": "UNITED STATES", "WASHINGTON": "UNITED STATES",
    "BRITAIN": "UNITED KINGDOM", "BRITISH": "UNITED KINGDOM", "LONDON": "UNITED KINGDOM",
    "SAUDI": "SAUDI ARABIA", "UAE": "UNITED ARAB EMIRATES",
    "RUSSIAN": "RUSSIA", "MOSCOW": "RUSSIA",
    "ISRAELI": "ISRAEL", "IRANIAN": "IRAN", "TEHRAN": "IRAN",
    "CHINESE": "CHINA", "BEIJING": "CHINA", "UKRAINIAN": "UKRAINE", "KYIV": "UKRAINE",
}


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip().upper()
    name = ALIASES.get(name, name)
    if len(name) < MIN_NAME_LEN or name in GENERIC:
        return None
    return name.title()


def run(conn: psycopg.Connection) -> None:
    wm = conn.execute(
        "SELECT watermark_ts FROM ingest_watermarks WHERE source = 'entities'"
    ).fetchone()
    rows = conn.execute(
        """
        SELECT e.id, e.event_type, e.actor1, e.actor2, e.importance, e.created_at
        FROM events e
        WHERE e.created_at > COALESCE(%s, '1970-01-01'::timestamptz)
          AND (e.actor1 IS NOT NULL OR e.actor2 IS NOT NULL)
        ORDER BY e.created_at
        LIMIT 5000
        """,
        (wm[0] if wm else None,),
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
    max_created = wm[0] if wm else None
    for event_id, event_type, actor1, actor2, importance, created_at in rows:
        max_created = created_at if max_created is None else max(max_created, created_at)
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
    if max_created is not None:
        conn.execute(
            """
            INSERT INTO ingest_watermarks (source, watermark_ts, updated_at)
            VALUES ('entities', %s, now())
            ON CONFLICT (source) DO UPDATE
                SET watermark_ts = EXCLUDED.watermark_ts, updated_at = now()
            """,
            (max_created,),
        )
    conn.commit()
    print(f"entities: {len(rows)} events processed, {mentions} mentions, {relations} relation updates")
