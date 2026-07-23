# World Simulator

A living map of the world, fed by news.

Instead of reading articles, you watch the planet. Feeds stream in, entities and events get extracted, and an interactive world map updates continuously: colored regions, animated arcs, storylines, indices, and a scrubbable timeline. The goal is to *follow the state of the world* the way you'd watch a strategy game, not scroll a news site.

**Status:** planning. See [PLAN.md](PLAN.md) for the full build plan and idea backlog.

## What it does (target state)

- **Ingests** GDELT (the backbone: pre-geocoded global events every 15 min), curated RSS feeds, and structured feeds (USGS earthquakes, GDACS disasters, NASA FIRMS fires).
- **Extracts** entities (people, orgs, places), event types, tone, and importance. Cheap NLP first, LLM enrichment on top for the events that matter.
- **Stores** everything in Postgres on Railway: events, entities, relations, storylines, and per-country state vectors.
- **Simulates**: each country/region carries persistent state (tension, stability, disaster level, economic mood) that events nudge and time decays. The map shows state, not just dots.
- **Renders** an interactive MapLibre GL map: choropleth layers, event markers, relation arcs, a time slider to replay history, storyline panels, and a HUD with global indices.

## Why this beats reading news

News is a firehose of disconnected articles. This turns it into:

1. **State, not stream.** Glance at the map, see what's tense, what's calm, what changed since yesterday.
2. **Storylines, not headlines.** Events cluster into ongoing narratives with arcs and timelines.
3. **Anomalies, not volume.** A protest in France is baseline; one in Singapore is a signal. The map highlights surprise, not noise.
4. **Replay.** Scrub back a month and watch a crisis spread.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Ingestion worker | Python 3.12, httpx, feedparser | Runs as a Railway cron/worker service |
| Extraction | spaCy NER + GDELT's own extraction, Claude Haiku for enrichment | Cheap tier always on, LLM tier only for high-signal events |
| Database | Postgres (Railway internal) | One source of truth; simple lat/lon columns first, PostGIS later if needed |
| API | FastAPI + SSE for live updates | Serves GeoJSON layers and storyline data |
| Frontend | MapLibre GL JS + Vite | Free vector tiles, no Mapbox token, WebGL performance |
| Deploy | Railway (api + worker + db in one project) | CLI already authenticated on this machine |

## Getting started

```bash
git clone git@github.com:dremok/world-simulator.git
cd world-simulator
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt   # created in Phase 0
cp .env.example .env                 # fill in values
```

Railway setup (CLI is already logged in as max.y.leander@gmail.com on this machine):

```bash
railway init          # create project "world-simulator"
railway add           # add Postgres plugin
railway up            # deploy
```

See [PLAN.md](PLAN.md) Phase 0 for the exact bootstrap sequence, schema, and service layout.

## Repo layout (planned)

```
world-simulator/
├── PLAN.md              # full build plan + creative backlog
├── CLAUDE.md            # instructions for Claude Code instances working here
├── ingest/              # feed pollers, GDELT sync, parsers
├── extract/             # NER, geocoding, LLM enrichment, storyline clustering
├── sim/                 # state vectors, decay model, indices
├── api/                 # FastAPI app, GeoJSON endpoints, SSE
├── web/                 # MapLibre frontend (Vite)
├── db/                  # migrations (raw SQL or alembic)
└── scripts/             # one-off utilities
```

## License

MIT
