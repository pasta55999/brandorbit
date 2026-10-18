# Architecture

```
                 +-------------------------------------------------------------+
                 |                    Streamlit UI (brandorbit/ui)              |
                 |  Overview | AI Visibility | Competitors | Brand Perception  |
                 |  Sources & Citations | Recommendations (actions, product    |
                 |  data) | Monitoring (runs, before/after, prompt explorer)  |
                 |  Settings (brand, catalogue, prompts, providers, data)      |
                 +------------------------------+------------------------------+
                                                |
        +----------------------+----------------+----------------+----------------------+
        v                      v                                 v                      v
+---------------+   +--------------------+              +-----------------+   +------------------+
| core/metrics  |   | analysis/          |              | audits/         |   | analysis/        |
| MetricValue   |   |  extraction (rules)|              |  catalogue_audit|   |  comparison      |
| RunMetrics    |   |  llm (optional)    |              |  website_audit  |   |  (before/after)  |
+-------+-------+   |  recommendations   |              |  report         |   +---------+--------+
        |           +---------+----------+              +--------+--------+             |
        |                     |                                  |                      |
        +----------+----------+----------------+-----------------+----------------------+
                   v                           v
          +-----------------+        +-------------------------+
          | storage/        |<-------| monitoring/runner       |
          | Repository      |        |  run_monitoring()       |
          | (SQLite, JSON   |        |  -> RawResponse (append)|
          |  documents)     |        |  -> Extraction          |
          +-----------------+        +-----------+-------------+
                                                 |
                                     +-----------v-------------+
                                     | providers/              |
                                     |  Provider (ABC)         |
                                     |  DemoProvider (fixtures)|
                                     |  OpenAIProvider (live)  |
                                     |  AnthropicProvider(live)|
                                     +-------------------------+
```

## Data flow

1. **Configure** - `Workspace` (brand, competitors), `Product` rows from a CSV, and
   `Prompt`s (manual, template or LLM-suggested; must be `approved` before monitoring).
2. **Monitor** - `run_monitoring()` sends each approved prompt to each selected provider,
   writes an immutable `RawResponse` (text, citations, status, latency, tokens, `source_kind`),
   logs the call, then stores a `deterministic` `Extraction` per response. Failures never abort
   the run; it ends as `partial`.
3. **Analyse** - `compute_run_metrics()` joins prompts + eligible responses + extractions.
   `build_findings()` applies rules over that join to produce `Finding`s with `Evidence`
   (prompt id, response id, verbatim quote, optional source URL). An optional LLM narrator may
   rewrite wording under schema validation but cannot add facts.
4. **Audit** - `audit_catalogue()` applies deterministic checks to the catalogue;
   `website_audit` reads a crawl snapshot or (opt-in) fetches up to five pages honouring
   robots.txt.
5. **Compare** - `compare_runs()` restricts both runs to common prompts, recomputes metrics,
   and diffs mentions, competitors, cited domains and wording per (prompt, provider).

## Key design rules

* **Raw vs derived.** `responses` is append-only; `extractions` and `findings` can be
  regenerated at any time from the raw rows ("Regenerate findings", `rerun_extraction`).
* **Evidence first.** Every finding carries response ids and quotes that are checked to exist
  verbatim in the stored text (`tests/test_metrics_and_storage.py::test_findings_are_grounded_in_stored_evidence`).
* **Demo is never silent.** Fixture answers carry `source_kind=demo_fixture`, the provider id
  is `demo-*`, the UI shows a banner and badge, and the demo provider returns an *error* for
  prompts without a fixture rather than inventing text.
* **Untrusted content.** Prompts, answers, catalogue rows and fetched HTML are data. LLM calls
  wrap them in delimited blocks with instructions to ignore embedded instructions; model output
  is validated with Pydantic; model-generated quotes must exist verbatim in the source or are
  dropped. No model output is ever executed or used to trigger external actions.
* **Bounded.** Per-run limits on prompts and calls, per-request timeout, bounded retries with
  backoff for retryable errors only, 2 MB / 2000-row catalogue limit, 5-page website fetch cap.

## Storage

SQLite file (`brandorbit.db` by default, override with `BRANDORBIT_DB`). Each table stores a
validated JSON document plus a few indexed columns. Tables: `workspaces`, `products`,
`prompts`, `runs`, `responses`, `extractions`, `findings`, `provider_logs`. No API keys or
secrets are stored.

## Extending

* **New provider** - subclass `providers.base.Provider`, implement `answer()` (and optionally
  `structured()`), register it in `providers/__init__.py::available_providers`.
* **New language** - `Prompt.language` and `BrandProfile.language` already exist; add a
  language-specific lexicon in `analysis/extraction.py` and language-aware templates.
* **New finding rule** - add a block in `analysis/recommendations.py::build_findings` that
  produces `Finding`s with `Evidence`; the grounding test will enforce traceability.
