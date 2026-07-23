-- Storyline lifecycle (from the endings/diff design): storylines carry an
-- explicit key for heuristic clustering, activity tracking for closure
-- detection, and a two-kind closure so the map never claims "resolved"
-- when the truth is "coverage went quiet".

ALTER TABLE storylines
    ADD COLUMN cluster_key      TEXT,          -- e.g. 'SD:conflict' (country:verb_class)
    ADD COLUMN last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN heat             REAL NOT NULL DEFAULT 0,   -- recent importance-weighted event rate
    ADD COLUMN closed_kind      TEXT CHECK (closed_kind IN ('resolved', 'quiet')),
    ADD COLUMN closed_summary   TEXT,
    ADD COLUMN narrated_at      TIMESTAMPTZ;   -- last time a narrator session touched it

CREATE UNIQUE INDEX storylines_active_key_idx
    ON storylines (cluster_key)
    WHERE status IN ('active', 'stale');

CREATE INDEX storylines_status_heat_idx ON storylines (status, heat DESC);
