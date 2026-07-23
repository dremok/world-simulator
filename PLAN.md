# World Simulator: Build Plan

The one-line pitch: **turn the global news firehose into a persistent, watchable world state.** Not a news reader. A map that knows what's going on.

This doc is the working plan. Phases 0-2 are concrete and should be built in order. Phase 3+ and the creative backlog are a menu; pick what's fun and high-signal.

---

## 1. Core architecture

```
┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐
│  Feeds       │──▶│  Ingest      │──▶│  Extract /   │──▶│  Postgres   │
│  GDELT, RSS, │   │  worker      │   │  Enrich      │   │  (Railway)  │
│  USGS, GDACS │   │  (cron 15m)  │   │  NLP + LLM   │   │             │
└─────────────┘   └──────────────┘   └──────────────┘   └──────┬──────┘
                                                               │
                                       ┌──────────────┐   ┌────▼────────┐
                                       │  Web map      │◀──│  FastAPI    │
                                       │  MapLibre GL  │   │  + SSE      │
                                       └──────────────┘   └─────────────┘
```

Three Railway services in one project:

1. **db**: Railway Postgres. Internal networking only, apps connect via `DATABASE_URL`.
2. **worker**: Python ingestion + extraction, run as a Railway cron service every 15 minutes (matching GDELT's update cadence). Idempotent: each run pulls new items since last watermark, dedupes, extracts, writes.
3. **api**: FastAPI. Serves GeoJSON layers, storyline/entity endpoints, and an SSE stream for live map updates. Also serves the built frontend as static files so the whole thing is one public URL.

Key design decision: **separate raw articles from derived events from simulated state.** Three tiers in the DB. Raw is append-only truth, events are extraction output (re-derivable if extraction improves), state is simulation output (re-derivable from events). You can rerun extraction or retune the simulation without re-fetching anything.

## 2. Data sources

Backbone first, garnish later.

### Tier 1: the backbone (Phase 1)

- **GDELT 2.0 Events + GKG** (free, no key, 15-min updates). This is the cheat code: it already does event coding (CAMEO taxonomy), actor extraction, geocoding, and tone scoring for worldwide media. You get "who did what to whom, where, with what tone" as CSV every 15 minutes. Start here; it makes the map interesting on day one without any LLM spend.
- **USGS earthquakes** (GeoJSON feed, free). Instant, reliable, geolocated. Great for testing the pipeline end to end.

### Tier 2: quality and locality (Phase 1-2)

- Curated RSS: Reuters, BBC World, AP, Al Jazeera, The Guardian. These are for the LLM enrichment tier, since GDELT tells you *that* something happened but headlines tell the story.
- Sweden: SVT, DN. Philippines: Rappler, ABS-CBN, PhilStar (Central Luzon matters: family in Tarlac, house in Porac).
- AI/tech layer: Hacker News API, arXiv cs.AI/cs.LG RSS.
- **GDACS** (disaster alerts, free XML/GeoJSON) and **NASA FIRMS** (active fires).

### Tier 3: later, if wanted

- ACLED (conflict event data, free key for research use), ReliefWeb API, Metaculus/Polymarket APIs (forecast layer), OpenSky (live flights, mostly for spectacle), Wikipedia current-events portal.

## 3. Database schema (v1)

```sql
sources(id, name, kind, url, country, trust_weight)
articles(id, source_id, url UNIQUE, title, published_at, fetched_at, raw_text, lang)
events(id, article_id NULL, gdelt_id NULL UNIQUE, event_type, cameo_code,
       actor1, actor2, lat, lon, country_iso, admin1,
       tone, goldstein, importance, occurred_at, created_at)
entities(id, name, kind,              -- person | org | place | country
         wikidata_id NULL, canonical_name)
entity_mentions(entity_id, event_id, role)
entity_relations(a_id, b_id, relation, weight, last_seen_at)
storylines(id, title, summary, status, started_at, updated_at, embedding vector NULL)
storyline_events(storyline_id, event_id)
country_state(country_iso, ts, tension, stability, disaster, econ_mood, attention)
indices(name, ts, value)              -- global gauges: conflict, disaster, ai_pace, ...
```

Notes:

- `events.importance`: computed score (source count x source trust x Goldstein magnitude x novelty). This is the main filter knob for everything downstream; the map shows the top-N, the LLM only enriches above a threshold.
- Start with plain lat/lon floats. Add PostGIS only when you need real spatial queries (Railway can run the `postgis/postgis` image if it comes to that).
- `pgvector` for storyline/article embeddings when semantic clustering lands (Phase 2). Railway Postgres supports it.

## 4. Extraction pipeline

Two tiers, so cost stays near zero at idle:

**Tier A (always on, free):** GDELT rows map almost directly into `events`. For RSS items: spaCy NER for entities, a country/city gazetteer for geocoding (the `geonamescache` + fallback lookup approach is enough), keyword rules for rough event typing.

**Tier B (LLM, gated by importance):** for events above the importance threshold, or when N sources cluster on the same thing, call Claude Haiku with a strict JSON schema: event type, actors and their roles, a one-sentence neutral summary, storyline assignment hint, severity 1-5, and "what changed" relative to the storyline so far. Batch these; a day of world news at threshold should cost cents.

**Storyline clustering (Phase 2):** embed event summaries (pgvector), greedy-attach each new event to the nearest active storyline within a similarity threshold, else open a new one. A nightly LLM pass renames storylines, merges duplicates, writes/updates the storyline summary, and closes stale ones. This is the feature that turns dots into narratives.

## 5. The simulation layer (what makes it a *simulator*)

Each country carries a state vector, updated on every worker run:

```
state[c] = decay(state[c], dt) + Σ impact(event) for events in c
```

- `impact` is a per-event-type kernel: protest bumps tension a little, armed conflict a lot, elections bump attention, disasters bump disaster, rate decisions bump econ_mood, etc. CAMEO codes and Goldstein scores give you this mapping nearly for free.
- `decay` pulls each dimension back toward a per-country baseline (France's protest baseline is high; Singapore's is near zero). Baselines are learned as rolling 90-day means, which is exactly what makes the **anomaly view** work: color by `(state - baseline) / std`, not by raw value.
- Snapshot `country_state` every run. That table is the time machine: the replay slider is just "query state at time T".

Global indices are aggregations over state plus dedicated detectors: Conflict Index, Disaster Index, Econ Stress, AI Acceleration (fed by the HN/arXiv layer), and a composite "World Tension" needle for the HUD.

## 6. Frontend

MapLibre GL JS + Vite. Free vector tiles (OpenFreeMap or Protomaps self-hosted pmtiles). No React needed at first; a single-page app with a few panels is fine.

Core UI:

- **Choropleth** layer, switchable: tension / disaster / econ mood / attention / anomaly (the default and the most interesting one).
- **Event markers** sized by importance, colored by type, clustered at low zoom. Click opens a card: neutral LLM summary, sources, storyline link.
- **Storyline panel**: active narratives ranked by heat, each with a sparkline and timeline.
- **HUD**: global index gauges along the top, plus a "last updated" pulse.
- **Time slider**: scrub the last 90 days, watch state evolve. Play button for animation.
- **SSE**: new high-importance events ping onto the map live with a ripple animation.

Aesthetic direction: dark map, restrained palette, Hopper-style stillness rather than dashboard-clutter. It should feel like a Tarkovsky war room, not a Bloomberg terminal.

## 7. Phases

### Phase 0: bootstrap (an evening)

1. `uv venv`, deps, `requirements.txt`, repo skeleton per README layout.
2. `railway init` (project `world-simulator`), `railway add` Postgres, set `ANTHROPIC_API_KEY` and config vars via `railway variables`.
3. Apply schema v1 (raw SQL in `db/migrations/`, applied by a tiny runner script).
4. USGS earthquakes → events table → FastAPI `/layers/events.geojson` → MapLibre page with dots. **Deploy this.** A live map of earthquakes on Railway on day one proves the whole pipe.

### Phase 1: the backbone (a weekend)

1. GDELT 15-min sync in the worker (events CSV → filter to importance threshold → upsert).
2. RSS poller for the Tier-2 feed list, article dedupe by URL + title similarity.
3. Importance scoring, country rollups, first choropleth (event volume + tone by country).
4. Railway cron wiring, watermark table, idempotency, basic logging.

### Phase 2: intelligence (1-2 weekends)

1. LLM enrichment tier with JSON schema output and batching.
2. Storyline clustering + nightly narrator pass.
3. Entity tables, entity dossier endpoint ("what do we know about X"), mention counts.
4. Event cards and storyline panel in the UI. Daily "world diff" summary endpoint.

### Phase 3: simulation (1-2 weekends)

1. State vectors, impact kernels, decay, learned baselines, anomaly choropleth.
2. Global indices + HUD gauges.
3. Time slider replay over `country_state` snapshots.

### Phase 4: the fun stuff

Pick from the backlog below.

## 8. Creative backlog (the ideas that make it special)

Ranked roughly by leverage-per-effort for making this *not just another news dashboard*:

1. **Anomaly-first coloring.** Already in the plan but worth stating as philosophy: the map's default question is "what's *unusual*?", not "what's loud?". This single choice is most of the product.
2. **Daily World Diff.** One LLM call each morning: "here's yesterday's state delta; write 10 bullets on what actually changed." Surfaced in the UI and pushable to Telegram. Replaces reading the news entirely, which is the stated goal.
3. **Relation arcs.** Animated great-circle arcs between countries/entities for sanctions, talks, attacks, aid, trade deals (deck.gl ArcLayer over MapLibre). Watching diplomacy as flowing light is the "strategy game" feel.
4. **Rashomon view.** Same storyline, sources from different geopolitical blocs side by side, with an LLM divergence note: "Western wires frame X as A; Chinese state media frames it as B; Al Jazeera leads with C." Bias made visible instead of hidden.
5. **Personal lenses.** Named filter presets: *AI* (HN/arXiv layer + chip supply chain events), *Portfolio* (events tagged to thematic bets: uranium, defense, water, semiconductors, India), *Sweden*, *Central Luzon* (typhoon/volcano/flood watch for Porac and Tarlac, genuinely useful). Lens = saved query + custom index gauge.
6. **World MCP server.** Expose `world_state(country)`, `storylines(topic)`, `what_changed(since)` as MCP tools over the same DB. Any Claude session on any machine can then ask "what's happening in the Philippines right now". Cheap to build once the API exists.
7. **Forecast layer.** Overlay Metaculus/Polymarket probabilities on relevant storylines. Later: have the LLM write weekly falsifiable predictions per storyline, store them, score them against what happens, and show its calibration curve. A simulator that predicts and gets graded.
8. **Time-lapse exports.** Render the last 90 days of the anomaly choropleth to a shareable 20-second MP4. Great demo artifact, trivially built from state snapshots.
9. **Sonification.** Ambient generative soundtrack driven by world state: base drone follows global tension, event types trigger instrument hits, regional pan follows longitude. There are radio sound generators in the personal-assistant workspace to borrow from. Uniquely Leanderz.
10. **Entity knowledge graph.** `entity_relations` is already a graph; render ego-networks on entity dossiers, run co-occurrence embeddings, and later GNN link prediction ("these two actors are about to interact"). Fits the GraphSAGE research thread.
11. **Day/night terminator + "quiet zones".** Subtle solar terminator overlay, and positive framing: regions with unusually *low* tension get a calm glow. The map shouldn't only know how to scream.
12. **Counterfactual mode.** For a selected storyline, LLM generates three plausible next-week scenarios with probabilities; kept and scored like the forecast layer. Reading these weekly beats most punditry.
13. **Attention vs. importance split-map.** Two small multiples: what media covers vs. what the importance model scores. The gap *is* the media-criticism feature; under-covered crises light up.
14. **Historical backfill.** GDELT goes back to 1979. Ingest key windows (fall of USSR, 9/11, Arab Spring, COVID) and let the replay slider time-travel decades. Turns the tool into a history machine.
15. **Weekly "world state" email.** Reuse the daily-briefing infrastructure from personal-assistant: Sunday evening summary with the week's diff, top storylines, index sparklines.

## 9. Costs and constraints

- GDELT, USGS, GDACS, FIRMS, HN, arXiv: free, no keys.
- LLM: Haiku-tier, gated by importance threshold; budget target under $5/month at defaults.
- Railway: hobby-tier friendly (worker is cron, not always-on; api is one small service; Postgres storage grows ~tens of MB/day at threshold, so add a retention/rollup job in Phase 2: raw articles pruned after 30 days, events kept, state snapshots kept forever since they're tiny).
- Map tiles: OpenFreeMap (free hosted) to start; self-host Protomaps pmtiles on Railway if rate limits bite.

## 10. Definition of done for the MVP

You open one URL. A dark world map shows colored countries (anomaly view), dots for today's important events, and a storyline sidebar. It updated itself 15 minutes ago without you touching anything. You hover Sweden, and it tells you what changed today in one sentence. You stop opening news sites.
