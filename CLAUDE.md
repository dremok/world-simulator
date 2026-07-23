# World Simulator: Claude Code Instructions

Read `PLAN.md` first. It contains the architecture, schema, data sources, phased plan, and idea backlog. Build phases in order (0 → 1 → 2 → 3), and within a phase work in small verified increments.

## Project state

Update this section as work progresses.

- **Current phase:** 0 (nothing built yet; repo contains only planning docs)
- **Next action:** Phase 0 step 1: repo skeleton + venv + requirements.txt

## Conventions

- Python 3.12, `uv` for everything (`uv venv`, `uv pip install`). Never install globally. Keep `requirements.txt` pinned and current.
- Raw SQL migrations in `db/migrations/NNN_name.sql`, applied by `scripts/migrate.py`. No ORM for v1; use `psycopg` with plain queries.
- Frontend: vanilla JS + MapLibre GL + Vite in `web/`. No React unless the UI genuinely outgrows it.
- Secrets live in `.env` locally (gitignored) and in Railway variables in production. Never commit keys.
- Worker must be idempotent: every ingest run reads a watermark, upserts, advances the watermark. Re-running is always safe.
- Three-tier data rule: raw articles are append-only truth, events are re-derivable extraction output, state is re-derivable simulation output. Never make raw depend on derived.

## Railway

- The Railway CLI is installed and logged in on this machine as max.y.leander@gmail.com (`railway whoami` to confirm).
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

## Owner context that shapes features

- Personal lenses (PLAN.md backlog #5) should include: AI/tech, portfolio themes (uranium, defense, clean water, semiconductors, robotics, India), Sweden (Lund/Malmö), and Central Luzon, Philippines (family in Tarlac, house in Porac; typhoon/volcano/flood alerts there are genuinely useful, not decorative).
- Aesthetic: dark, still, restrained. Anomaly view is the default lens. See PLAN.md section 6.
- Writing style for any user-facing or shareable text: no em dashes, no AI-slop phrasing, human register.
