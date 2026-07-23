---
name: enrich
description: Enrich world-simulator events with neutral one-sentence summaries and severity, using this Claude session as the LLM (zero API cost). Use when Max says /enrich, "update the summaries", "enrich events", or "run the LLM stuff".
---

# Enrich events

You are the enrichment model. No Anthropic API calls, no API keys — you
generate the summaries in-session and write them back through the plumbing
in `extract/enrich.py`.

## Steps

1. Get pending events (highest importance first):

       .venv/bin/python -m extract.enrich pending 40 > /tmp/pending.json

   Each item has: id, event_type (CAMEO root, often miscoded — trust the
   article, not the code), actors, country, tone, goldstein, payload.url.

2. For each event, fetch the source article (WebFetch on payload.url; skip
   events whose URL is dead or paywalled — leave them un-enriched rather
   than guessing). From the article write:
   - `summary`: ONE neutral sentence, factual register, no em dashes, no
     editorializing. What happened, who, where. If the GDELT event_type
     contradicts the article (e.g. "fight" on a cancer-research story),
     the summary reflects the article.
   - `severity`: integer 1-5. 1 = routine news, 3 = notable regional
     event, 5 = major loss of life / war escalation / state collapse.

3. Batch the results as a JSON array and apply:

       echo '[{"id": 123, "summary": "...", "severity": 2}, ...]' | \
         .venv/bin/python -m extract.enrich apply

4. Verify: re-run `pending` and confirm the applied ids are gone, then
   spot-check one summary on the live map popup.

## Rules

- Summaries must come from the fetched article, never from the CAMEO code
  or URL slug alone. An unfetchable article means no summary.
- Batch WebFetch calls in parallel where possible; ~20-40 events per run
  keeps a session fast.
- This skill writes to the production DB (DATABASE_URL in .env). That is
  intended.
