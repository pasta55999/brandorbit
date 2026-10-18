# BrandOrbit evaluation

This document describes how the extraction and analysis pipeline was evaluated, the actual
numbers produced by `python -m evaluation.run_eval` on 2026-10-18, known failure cases and
limitations. Nothing in this file is estimated; every number is reproducible from the
repository.

## 1. What is evaluated

BrandOrbit's analytical core is the extraction step that turns a raw AI answer into
structured data: which brands are mentioned, in what order, with what sentiment, which
sources are cited, and which product claims are made and whether they agree with the
catalogue. All dashboard metrics are derived from these extractions, so their quality
bounds the quality of everything downstream.

Two deterministic approaches are compared:

| Method | Description |
|---|---|
| `naive` | Case-insensitive substring match on the canonical brand name only. No aliases, sentiment, claims or inline-URL detection. This is the floor. |
| `deterministic` | Word-boundary alias + domain matching, sentence-level evidence quotes, list-rank detection, lexicon sentiment with negation/hedge handling, regex claim extraction with nearest-subject attribution, verification against the catalogue. This is what the app uses. |
| `llm` | Schema-validated LLM extraction (`LLMExtractionOutput`) with verbatim-quote enforcement. Requires a live provider. |

## 2. Methodology

* **Labelled set**: `data/eval/labelled_responses.json` - 24 synthetic answers written for the
  fictional demo brand, each hand-labelled with: the set of brands mentioned, target sentiment,
  whether the brand website is cited, the expected `(attribute, verification_status)` of each
  product claim, and where relevant list rank, recommendation flags and eligibility.
* **Coverage of required scenarios**: brand mentioned / not mentioned (e01, e02), alias- and
  domain-only mentions (e03, e04), competitor recommended while brand absent (e05), positive /
  negative / neutral / ambiguous descriptions (e01, e06, e07, e08), incorrect price and warranty
  (e09, e10), correct specifications (e11), budget bound that must not be read as a price (e12),
  multi-brand sentence price attribution (e13), unverifiable product (e14), missing citations
  (e15), third-party-only citation (e16), inline URL citation (e17), negated recommendation
  (e18), substring false-positive guard (e19), numbered list rank (e20), malformed output (e21),
  API failure (e22), fabricated/unsupported citation (e23), and a deliberately included known
  failure where a competitor alias collides with a person's name (e24).
* **Scoring**: brand mentions are scored as a set per answer (precision/recall over all
  brand-answer pairs). Sentiment accuracy is scored on answers where the target is mentioned.
  Claim recall counts `(attribute, status)` pairs; "extra" counts claims that were extracted
  but not labelled. Ineligible responses must yield an empty extraction with confidence 0.
* **Reproduce**: `python -m evaluation.run_eval` (add `--llm` with an API key configured).
  `tests/test_extraction.py::test_evaluation_thresholds` enforces regression thresholds.

## 3. Results (2026-10-18)

| Metric | naive | deterministic | llm |
|---|---|---|---|
| Brand-mention precision | 1.000 (tp=27, fp=0) | 0.970 (tp=32, fp=1) | not run |
| Brand-mention recall | 0.844 (fn=5) | 1.000 (fn=0) | not run |
| Brand-mention F1 | 0.915 | 0.985 | not run |
| Target sentiment accuracy | 1/15 (no sentiment model) | 16/19 = 0.842 | not run |
| Website-citation detection | 21/22 | 22/22 | not run |
| Claim (attribute, status) recall | 0/14 | 14/14, 0 extra | not run |
| List-rank detection | 0/1 | 1/1 | not run |
| Recommendation flag | 1/2 | 2/2 | not run |
| Ineligible responses excluded | 0/2 | 2/2 | not run |

Deterministic sentiment confusion (expected -> got): negative->negative 3, neutral->neutral 9,
positive->positive 3, positive->neutral 2, positive->uncertain 1, uncertain->uncertain 1.

**The LLM-assisted method was not run.** No API key was available in the build environment,
and the project rule is to never present fabricated results. The code path exists
(`brandorbit/analysis/llm.py`) and is unit-tested with a fake provider for its safety
behaviour (non-verbatim quotes are dropped, unknown brands are dropped, malformed JSON yields a
zero-confidence extraction). Running `python -m evaluation.run_eval --llm` with
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` set will append its results.

## 4. Failure cases (deterministic)

| Case | What happened | Why | Mitigation / status |
|---|---|---|---|
| e24 person-name collision | "Zayna, a Dubai-based food blogger" matched the competitor alias *Zayna* | Alias matching cannot disambiguate a short alias from a first name | Known limitation. Users can remove short aliases; an LLM pass could resolve entity type. Kept in the set deliberately. |
| e12 "fits comfortably" | Expected positive, got neutral | Lexicon has no cue for "fits comfortably" | Lexicon sentiment is intentionally conservative; hedged/unknown phrasing defaults to neutral rather than guessing. |
| e16 "According to a local review site ... solid" | Expected positive, got uncertain | "according to" is treated as a hedge, and with only one positive cue the classifier downgrades to uncertain | Arguably correct behaviour: a second-hand opinion is less certain. Label kept as positive to record the disagreement. |
| e20 list item | Expected positive (brand appears in a "Best air fryers" list), got neutral | Sentiment is computed over sentences containing the brand; the list item itself has no sentiment words. The list heading is a separate sentence. | Could be improved by inheriting sentiment from the heading of a numbered list. |

Failure cases for the naive baseline are, as expected, all alias/domain misses (e03, e04, e09,
e11), inline-URL misses (e17), and the absence of sentiment/claim extraction.

## 5. Other things that were tested

* **Metric calculations** - unit tests check mention rate, citation rate, share of voice,
  competitor gap and the exclusion of failed answers from denominators against hand-computed
  values (`tests/test_metrics_and_storage.py`).
* **Schema validation** - invalid URLs, duplicate brand names, findings with malformed IDs, and
  LLM outputs without quotes are rejected.
* **Evidence traceability** - every stored finding in the demo workspace is checked: each
  evidence item points to an existing response for the same prompt, each quote exists verbatim
  in that response's raw text, each source URL is one of that response's citations.
* **Recommendation grounding** - the LLM narrator is tested to reject outputs that use quotes
  not present in the evidence.
* **Persistence** - raw responses are append-only (second insert with the same id raises);
  finding statuses survive regeneration.
* **Missing data** - metrics return `n/a` with denominator 0; demo providers return a labelled
  error rather than a fabricated answer for unknown prompts; partial runs are recorded as
  `partial` with per-call logs.
* **Before/after comparison** - the fixture pair yields exactly the designed 4 gained / 1 lost
  mentions and 2 coverage mismatches (one timeout, one malformed answer).
* **UI** - every page is rendered headlessly with Streamlit `AppTest` against a temporary
  database (`tests/test_ui_smoke.py`).

Run everything with `pytest` (50 tests at the time of writing).

## 6. Limitations of this evaluation

* The labelled set is small (24 cases) and was written by the same author as the extractor;
  it demonstrates behaviour on designed scenarios rather than estimating real-world accuracy.
* The demo fixtures and the evaluation set are synthetic. Real AI answers are longer, more
  varied in formatting, and mention brands across sentences (e.g. "the 5.5L model costs AED
  329" two sentences after the brand name) - the deterministic claim extractor only links
  values to a brand within one sentence and will under-count such claims.
* Sentiment is lexicon-based and English-only. It is adequate for triage and is labelled with
  confidence, but should not be read as a precise measurement.
* Verification compares against the user-supplied catalogue, which can itself be wrong or stale
  (the demo catalogue deliberately contains such inconsistencies, surfaced by the audit).
* No claim is made that BrandOrbit improves AI visibility. The before/after fixture run
  simulates plausible changes to exercise the comparison view and is explicitly labelled as
  simulated.
