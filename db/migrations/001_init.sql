-- Schema v1. Three tiers: raw (sources, articles) -> derived (events, entities,
-- storylines) -> simulated (country_state, indices). Raw never depends on derived.

CREATE TABLE sources (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL,          -- gdelt | rss | usgs | gdacs | firms | hn | arxiv
    url          TEXT,
    country      TEXT,                   -- ISO 3166-1 alpha-2, NULL for global
    trust_weight REAL NOT NULL DEFAULT 1.0,
    UNIQUE (name)
);

CREATE TABLE articles (
    id           BIGSERIAL PRIMARY KEY,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    url          TEXT NOT NULL UNIQUE,
    title        TEXT,
    published_at TIMESTAMPTZ,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_text     TEXT,
    lang         TEXT
);

CREATE TABLE events (
    id           BIGSERIAL PRIMARY KEY,
    article_id   BIGINT REFERENCES articles(id),
    external_id  TEXT UNIQUE,            -- namespaced upstream id: 'usgs:us7000abcd', 'gdelt:123456789'
    event_type   TEXT NOT NULL,          -- earthquake | protest | conflict | ...
    cameo_code   TEXT,
    actor1       TEXT,
    actor2       TEXT,
    lat          DOUBLE PRECISION,
    lon          DOUBLE PRECISION,
    country_iso  TEXT,
    admin1       TEXT,
    tone         REAL,
    goldstein    REAL,
    importance   REAL NOT NULL DEFAULT 0,
    occurred_at  TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload      JSONB                   -- upstream extras (magnitude, depth, alert level, ...)
);

CREATE INDEX events_occurred_at_idx ON events (occurred_at DESC);
CREATE INDEX events_importance_idx  ON events (importance DESC);
CREATE INDEX events_country_idx     ON events (country_iso);

CREATE TABLE entities (
    id             BIGSERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,        -- person | org | place | country
    wikidata_id    TEXT,
    canonical_name TEXT,
    UNIQUE (name, kind)
);

CREATE TABLE entity_mentions (
    entity_id BIGINT NOT NULL REFERENCES entities(id),
    event_id  BIGINT NOT NULL REFERENCES events(id),
    role      TEXT,
    PRIMARY KEY (entity_id, event_id)
);

CREATE TABLE entity_relations (
    a_id         BIGINT NOT NULL REFERENCES entities(id),
    b_id         BIGINT NOT NULL REFERENCES entities(id),
    relation     TEXT NOT NULL,
    weight       REAL NOT NULL DEFAULT 1.0,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (a_id, b_id, relation)
);

-- embedding column arrives with pgvector in Phase 2
CREATE TABLE storylines (
    id         BIGSERIAL PRIMARY KEY,
    title      TEXT NOT NULL,
    summary    TEXT,
    status     TEXT NOT NULL DEFAULT 'active',   -- active | stale | closed
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE storyline_events (
    storyline_id BIGINT NOT NULL REFERENCES storylines(id),
    event_id     BIGINT NOT NULL REFERENCES events(id),
    PRIMARY KEY (storyline_id, event_id)
);

CREATE TABLE country_state (
    country_iso TEXT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    tension     REAL NOT NULL DEFAULT 0,
    stability   REAL NOT NULL DEFAULT 0,
    disaster    REAL NOT NULL DEFAULT 0,
    econ_mood   REAL NOT NULL DEFAULT 0,
    attention   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (country_iso, ts)
);

CREATE TABLE indices (
    name  TEXT NOT NULL,
    ts    TIMESTAMPTZ NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (name, ts)
);

-- One watermark per ingest source; every run reads it, upserts, advances it.
CREATE TABLE ingest_watermarks (
    source       TEXT PRIMARY KEY,       -- 'usgs', 'gdelt', ...
    watermark_ts TIMESTAMPTZ NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
