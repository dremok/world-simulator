-- CAMEO actor country codes (3-letter, e.g. USA, RUS) straight from GDELT.
-- These power relation mode: "show me everything between A and B".

ALTER TABLE events
    ADD COLUMN actor1_cc TEXT,
    ADD COLUMN actor2_cc TEXT;

CREATE INDEX events_actor_pair_idx ON events (actor1_cc, actor2_cc)
    WHERE actor1_cc IS NOT NULL AND actor2_cc IS NOT NULL;
