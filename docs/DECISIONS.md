# Design decisions

**Single Streamlit app, no FastAPI.** The workflow is single-user and local; a separate API
would add deployment surface without improving the product. The package boundaries
(`core`, `providers`, `monitoring`, `analysis`, `audits`, `storage`, `ui`) keep the logic
independent of Streamlit so an API could be added later.

**SQLite with JSON documents.** Schemas are still evolving; validated JSON per row with a few
indexed columns gives flexibility and keeps the repository under 300 lines. Pydantic validates
on write and read, so a schema change surfaces immediately.

**Deterministic extraction by default, LLM as an option.** Rule-based extraction is
reproducible, free, offline and auditable, and on the labelled set it reaches recall 1.0 /
precision 0.97 for brand mentions with full claim recall. Its weaknesses (short alias
collisions, cross-sentence claims, lexicon sentiment) are documented, and an LLM extractor with
the same output schema can be enabled for comparison when a key is present.

**Rules generate findings; the LLM may only narrate.** Findings must be traceable to stored
evidence. Rules produce the evidence set; the LLM narrator receives only that evidence and
its output is rejected if it cites quotes outside it. This avoids invented quotations and
keeps the "why was this generated?" panel honest.

**Fictional demo data.** Real competitor brands and reviewer sites would be either defamed or
misrepresented by fabricated answers. Everything in the demo workspace is fictional and
labelled, and the demo provider refuses to answer prompts that have no fixture.

**Eligible-answer denominators.** Counting failed calls as "not mentioned" would silently
depress visibility metrics on a bad network day. Failures are excluded from denominators and
surfaced as coverage instead.

**Prompt-level competitor gap.** A competitor gap is a prompt (customer need), not an answer.
If one provider names the brand and another does not, the need is still being served somewhere,
so it is not a gap; it does show up in the per-provider mention rates.

**Hypotheses, not promises.** Every recommendation's expected outcome is phrased as a hypothesis
and the comparison view carries a causation disclaimer. Model outputs vary run to run even with
no change on the brand side.

**Website fetching is opt-in.** The audit works from a snapshot CSV by default. Live fetching is
limited to five pages, honours robots.txt, uses a descriptive user agent and only parses JSON-LD,
title, meta description and price. No AI platforms are scraped.
