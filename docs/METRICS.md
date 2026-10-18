# Metric definitions

All metrics are computed in `brandorbit/core/metrics.py` from stored responses and
extractions. Every metric is returned as a `MetricValue` with numerator, denominator and
definition, and the UI always shows the sample size next to the number.

## Eligibility and coverage

An **eligible answer** is a stored `RawResponse` with `status == ok` and non-empty text.
Answers with status `error`, `timeout`, `rate_limited` or `malformed` are:

* stored (with the error message) so the run is auditable,
* **excluded from every denominator**,
* counted in `Coverage.failed` and shown in the coverage line of each page.

A run is marked `completed`, `partial` (some calls failed) or `failed` (all calls failed).
When comparing runs, metrics are restricted to prompts present in both runs, and a warning is
shown if the number of eligible answers differs.

## Metrics

| Metric | Numerator | Denominator | Notes |
|---|---|---|---|
| **Mention rate** | eligible answers that mention the brand (any alias or domain, word-boundary match) | eligible answers | Also computed per provider, per prompt category, and per competitor. |
| **Citation rate** | eligible answers whose citations (provider-returned or inline URLs) include the brand's website domain | eligible answers | Providers without web search return no citations; those answers still count in the denominator. |
| **Share of voice** | number of eligible answers mentioning the brand (max one per brand per answer) | total of the same count across the target and all configured competitors | Measures relative presence among configured brands only; unknown brands are not detected. |
| **Competitor gap** | prompts where at least one competitor is mentioned in some eligible answer and the target in none | prompts with any competitor mention | Computed at prompt level, not answer level. |
| **Brand accuracy rate** | claims about the target brand verified as correct against the catalogue | verified + conflicting claims | `unverifiable` (no matching product/attribute) and `inconclusive` claims are reported separately and excluded. |
| **Average position** | mean of the target's position (order of first appearance among detected brands, 1 = first) | answers mentioning the target | Not a rank in a list; `list_rank` is captured separately when a numbered list is present. |
| **Recommended** | answers where the sentences mentioning the brand contain recommendation language and are not negated | - | Distinct from being mentioned. |

Mention rate, position, citation rate and share of voice measure different things and are
never combined into a single score.

## Claim verification statuses

| Status | Meaning |
|---|---|
| `verified` | Value matches the catalogue (price within 0.5; numeric attributes within 0.05). |
| `conflict` | A matching product/attribute exists in the catalogue and the value differs. |
| `unverifiable` | No matching product, product match is ambiguous, or the catalogue has no value for that attribute. |
| `inconclusive` | A trusted value exists but could not be compared numerically. |

Brand-level warranty claims ("Seraj Home offers a 1-year warranty") are compared with the
modal catalogue warranty only when that value covers at least 80% of products that have one.

## Scope statement

Results reflect the specific provider, model, API configuration, prompt wording and time of
each run. They are not a measurement of what every user of ChatGPT, Google or any other
consumer product sees. Differences between runs do not establish causation.
