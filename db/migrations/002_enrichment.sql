-- LLM enrichment output. Derived tier: always re-derivable, never load-bearing
-- for ingest. Populated by the /enrich Claude Code skill (no API calls).

ALTER TABLE events
    ADD COLUMN summary     TEXT,
    ADD COLUMN severity    SMALLINT CHECK (severity BETWEEN 1 AND 5),
    ADD COLUMN enriched_at TIMESTAMPTZ;

CREATE INDEX events_needs_enrichment_idx
    ON events (importance DESC)
    WHERE enriched_at IS NULL;
