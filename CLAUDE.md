# World Simulator: Claude Code Instructions

Read `PLAN.md` first. It contains the architecture, schema, data sources, phased plan, and idea backlog. Build phases in order (0 → 1 → 2 → 3), and within a phase work in small verified increments.

## Project state

Update this section as work progresses.

- **Current phase:** 2 in progress. Live at https://api-production-8a0f.up.railway.app. Done: full Phase 1 (GDELT cron-verified in prod, RSS poller, choropleth, legend); enrichment plumbing + /enrich skill (zero API cost, session is the LLM); heuristic storyline clustering (country×verb-class keys, active/stale/closed lifecycle, quiet-vs-resolved closure), storyline panel with click-to-isolate, /storylines + /diff endpoints, first narration pass applied.
- **Next action:** Phase 2 continued: entity tables ingestion + relation mode (/api/relation, actor-pair arcs — run the GDELT actor-recall probe first, see ideation notes), event cards, daily world-diff surface. Storyline clustering v2 (actor-aware keys) once entities land.
- **Decision (2026-07-23):** LLM enrichment will run on demand via a Claude Code skill instead of API calls from the worker, to keep API spend at zero. Build `extract/enrich.py` as an idempotent module behind a driver boundary; `ENRICH_ENABLED=false` default in the deployed worker.

## Architecture in one breath

Feeds (GDELT, RSS, USGS, GDACS) → `ingest/` worker (Railway cron, 15 min) → `extract/` (spaCy + gated Haiku enrichment) → Postgres → `sim/` (per-country state vectors) → `api/` (FastAPI, GeoJSON + SSE) → `web/` (MapLibre map). Planned dirs not yet created: `ingest/`, `extract/`, `sim/`, `api/`, `web/`, `db/migrations/`, `scripts/`. Put new code in the matching stage; details in PLAN.md sections 1-6.

## Commands

```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env                     # config knobs: IMPORTANCE_THRESHOLD, GDELT_ENABLED, RSS_ENABLED

# Develop (all commands below exist from Phase 0/1 onward)
python scripts/migrate.py                # apply db/migrations/*.sql in order
railway run python -m ingest.run         # one worker run against the Railway DB
uvicorn api.main:app --reload            # API locally
npm run dev                              # frontend, from web/

# Deploy
railway up
```

## Conventions

- Python 3.12, `uv` for everything (`uv venv`, `uv pip install`). Never install globally. Keep `requirements.txt` pinned and current.
- Raw SQL migrations in `db/migrations/NNN_name.sql`, applied by `scripts/migrate.py`. No ORM for v1; use `psycopg` with plain queries.
- Frontend: vanilla JS + MapLibre GL + Vite in `web/`. No React unless the UI genuinely outgrows it.
- Secrets live in `.env` locally (gitignored) and in Railway variables in production. Never commit keys.
- Worker must be idempotent: every ingest run reads a watermark, upserts, advances the watermark. Re-running is always safe.
- Three-tier data rule: raw articles are append-only truth, events are re-derivable extraction output, state is re-derivable simulation output. Never make raw depend on derived.

## Railway

- The Railway CLI is installed and logged in on this machine (`railway whoami` to confirm).
- One Railway project, `world-simulator`, with three services: `api` (FastAPI + static frontend), `worker` (cron every 15 min), `db` (Postgres plugin).
- `railway init` has NOT been run yet; that's part of Phase 0.
- Use `railway variables` to set `ANTHROPIC_API_KEY` and config. Apps read `DATABASE_URL` from Railway's injected env.
- Add `pgvector` when Phase 2 storyline clustering lands (Railway Postgres supports it via `CREATE EXTENSION vector`).

## LLM usage

- Enrichment model: Claude Haiku (`claude-haiku-4-5-20251001` or newer). Always request strict JSON via a schema, always batch, and only enrich events above the importance threshold. Budget target: under $5/month.
- Check current model ids and API details with the `claude-api` skill or Context7 before writing SDK code; don't trust memory.

## Verification habits

- After every ingest change: run the worker once locally against the Railway DB (`railway run python -m ingest.run`) and check row counts before and after.
- After every API change: curl the endpoint and eyeball the GeoJSON.
- After every frontend change: load the map locally (`npm run dev` in `web/`) and look at it.
- Deploy early. The Phase 0 goal is a live earthquake map on a public Railway URL; keep it deployable from then on.

## Product principles

- This is a general tool, not a personal dashboard. Anything user-specific (feed lists, lenses, regions of interest) belongs in config or the DB, never hardcoded.
- Aesthetic: dark, still, restrained. Anomaly view is the default lens. See PLAN.md section 6.
- Writing style for any user-facing or shareable text: no em dashes, no AI-slop phrasing, human register.
