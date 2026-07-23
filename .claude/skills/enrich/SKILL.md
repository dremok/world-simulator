---
name: enrich
description: Enrich world-simulator events with neutral one-sentence summaries and severity, using this Claude session as the LLM (zero API cost). Use when Max says /enrich, "update the summaries", "enrich events", or "run the LLM stuff".
---

# Enrich events

You are the enrichment model. No Anthropic API calls, no API keys — you
generate the summaries in-session and write them back through the plumbing
in `extract/enrich.py`.

## Steps (standardized, repeatable)

1. Fetch pending events WITH extracted article text (one command; dead or
   blocked URLs are auto-marked fetch_failed and never retried):

       .venv/bin/python -m extract.enrich fetch 60 > /tmp/enrich_work.json

   Each item: event_ids (several events often share one article), url,
   event_type (CAMEO root, often miscoded — trust the article), actors,
   country, article_excerpt (trafilatura-extracted main text).

2. Read /tmp/enrich_work.json and for each item write, FROM THE EXCERPT:
   - `summary`: ONE neutral sentence, factual register, no em dashes, no
     editorializing. What happened, who, where. If the GDELT event_type
     contradicts the article (e.g. "fight" on a cancer-research story),
     the summary reflects the article.
   - `severity`: integer 1-5. 1 = routine news, 3 = notable regional
     event, 5 = major loss of life / war escalation / state collapse.

3. Apply (keep event_ids as given, one object per article):

       echo '[{"event_ids": [123, 124], "summary": "...", "severity": 2}, ...]' | \
         .venv/bin/python -m extract.enrich apply

4. Verify: `fetch 5` again and confirm the queue shrank, then spot-check
   one summary on the live map popup.

## Narrating storylines (same session, second pass)

5. Get storylines needing narration (new activity since last narration):

       .venv/bin/python -m extract.enrich narrate-pending 20 > /tmp/narr.json

   Each has cluster_key (country:verb_class), heat, and its top 12 events.

6. For each storyline write a specific `title` (5-8 words naming actors
   and what is actually happening, not "conflict · US") and a 2-3 sentence
   neutral `summary` of the arc so far. For storylines with
   status=closed: write `closed_summary` (what happened, how it ended)
   and set `closed_kind` to "resolved" ONLY if the events show an actual
   terminal event (ceasefire signed, verdict, election concluded);
   otherwise leave it "quiet". Never upgrade quiet to resolved on a guess.

7. Apply: `... | .venv/bin/python -m extract.enrich narrate-apply`

## Rules

- Summaries must come from the fetched article, never from the CAMEO code
  or URL slug alone. An unfetchable article means no summary.
- Batch WebFetch calls in parallel where possible; ~20-40 events per run
  keeps a session fast.
- This skill writes to the production DB (DATABASE_URL in .env). That is
  intended.
