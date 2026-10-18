"""Visibility and competitor metrics.

Every metric is returned as a ``MetricValue`` carrying its numerator, denominator and a
plain-English definition so the UI can always show the sample size next to the number.

Definitions (see docs/METRICS.md):

* Eligible answer: a stored response with status ``ok`` and non-empty text. Failed, timed-out
  or malformed responses are *excluded from the denominator* and counted separately as
  ``coverage.failed``.
* Mention rate       = eligible answers mentioning brand / eligible answers.
* Citation rate      = eligible answers citing the brand's website domain / eligible answers.
* Share of voice     = brand mentions / all detected brand mentions (target + competitors),
                       counting at most one mention per brand per answer.
* Competitor gap     = prompts (not answers) where >= 1 competitor is mentioned in at least
                       one eligible answer and the target brand appears in none of them.
* Brand accuracy     = claims verified correct / (verified + conflicting) claims. Unverifiable
                       and inconclusive claims are reported but excluded from the ratio.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from brandorbit.core.schemas import Extraction, Prompt, PromptCategory, RawResponse, Sentiment, VerificationStatus, Workspace


@dataclass
class MetricValue:
    name: str
    numerator: int
    denominator: int
    definition: str
    unit: str = "%"

    @property
    def value(self) -> Optional[float]:
        return None if self.denominator == 0 else round(100.0 * self.numerator / self.denominator, 1)

    @property
    def display(self) -> str:
        return "n/a" if self.value is None else f"{self.value:.1f}%"

    @property
    def sample(self) -> str:
        return f"{self.numerator}/{self.denominator}"


@dataclass
class Coverage:
    prompts: int
    providers: list[str]
    responses_total: int
    eligible: int
    failed: int
    by_status: dict[str, int]

    @property
    def is_complete(self) -> bool:
        return self.failed == 0


@dataclass
class AnswerRecord:
    """One eligible answer joined with its prompt and extraction."""

    response: RawResponse
    prompt: Prompt
    extraction: Extraction

    @property
    def brands_mentioned(self) -> set[str]:
        return {m.brand for m in self.extraction.mentions}


@dataclass
class RunMetrics:
    coverage: Coverage
    mention_rate: MetricValue
    citation_rate: MetricValue
    share_of_voice: dict[str, MetricValue]
    competitor_gap_prompts: list[str]
    competitor_gap: MetricValue
    accuracy: MetricValue
    inaccurate_claims: int
    unverifiable_claims: int
    sentiment_counts: dict[str, int]
    by_provider: dict[str, dict[str, MetricValue]] = field(default_factory=dict)
    by_category: dict[str, dict[str, MetricValue]] = field(default_factory=dict)
    absent_prompt_ids: list[str] = field(default_factory=list)
    competitor_mention_rate: dict[str, MetricValue] = field(default_factory=dict)
    competitor_citation_rate: dict[str, MetricValue] = field(default_factory=dict)
    avg_position: Optional[float] = None


def join_records(prompts: list[Prompt], responses: list[RawResponse], extractions: list[Extraction]) -> tuple[list[AnswerRecord], Coverage]:
    pmap = {p.id: p for p in prompts}
    emap = {e.response_id: e for e in extractions}
    status_counts = Counter(r.status.value for r in responses)
    records = [
        AnswerRecord(r, pmap[r.prompt_id], emap[r.id])
        for r in responses
        if r.is_eligible and r.prompt_id in pmap and r.id in emap
    ]
    cov = Coverage(
        prompts=len({r.prompt_id for r in responses}),
        providers=sorted({r.provider for r in responses}),
        responses_total=len(responses),
        eligible=len(records),
        failed=sum(1 for r in responses if not r.is_eligible),
        by_status=dict(status_counts),
    )
    return records, cov


def _rate(name: str, hits: int, total: int, definition: str) -> MetricValue:
    return MetricValue(name, hits, total, definition)


def mention_rate(records: list[AnswerRecord], brand: str) -> MetricValue:
    hits = sum(1 for r in records if brand in r.brands_mentioned)
    return _rate("Mention rate", hits, len(records), f"Eligible answers that mention {brand}")


def citation_rate(records: list[AnswerRecord], domain: str, brand: str) -> MetricValue:
    hits = sum(1 for r in records if domain in r.extraction.cited_domains)
    return _rate("Citation rate", hits, len(records), f"Eligible answers citing {domain} ({brand})")


def share_of_voice(records: list[AnswerRecord], brands: list[str]) -> dict[str, MetricValue]:
    counts = Counter()
    for r in records:
        for b in r.brands_mentioned:
            counts[b] += 1
    total = sum(counts[b] for b in brands)
    return {b: _rate("Share of voice", counts[b], total, "Brand's share of all detected brand mentions (max one per brand per answer)") for b in brands}


def competitor_gaps(records: list[AnswerRecord], workspace: Workspace) -> list[str]:
    """Prompt ids where a competitor is mentioned in some eligible answer and the target in none."""
    by_prompt: dict[str, list[AnswerRecord]] = defaultdict(list)
    for r in records:
        by_prompt[r.prompt.id].append(r)
    comps = {c.name for c in workspace.competitors}
    gaps = []
    for pid, recs in by_prompt.items():
        brands = set().union(*(r.brands_mentioned for r in recs))
        if brands & comps and workspace.brand.name not in brands:
            gaps.append(pid)
    return sorted(gaps)


def absent_prompts(records: list[AnswerRecord], target: str) -> list[str]:
    by_prompt: dict[str, bool] = defaultdict(bool)
    for r in records:
        by_prompt[r.prompt.id] = by_prompt[r.prompt.id] or (target in r.brands_mentioned)
    return sorted(pid for pid, present in by_prompt.items() if not present)


def accuracy(records: list[AnswerRecord]) -> tuple[MetricValue, int, int]:
    verified = conflict = unverifiable = 0
    for r in records:
        for c in r.extraction.claims:
            if c.verification_status == VerificationStatus.verified:
                verified += 1
            elif c.verification_status == VerificationStatus.conflict:
                conflict += 1
            else:
                unverifiable += 1
    return (
        _rate("Brand accuracy rate", verified, verified + conflict, "Verified claims / (verified + conflicting) claims about the target brand"),
        conflict,
        unverifiable,
    )


def sentiment_counts(records: list[AnswerRecord], target: str) -> dict[str, int]:
    counts = {s.value: 0 for s in Sentiment}
    for r in records:
        for m in r.extraction.mentions:
            if m.brand == target:
                counts[m.sentiment.value] += 1
    return counts


def compute_run_metrics(workspace: Workspace, prompts: list[Prompt], responses: list[RawResponse], extractions: list[Extraction]) -> RunMetrics:
    records, cov = join_records(prompts, responses, extractions)
    target = workspace.brand.name
    domain = workspace.brand.domain
    brands = workspace.all_brands()
    acc, conflicts, unverifiable = accuracy(records)
    gaps = competitor_gaps(records, workspace)
    prompts_with_any_competitor = len({r.prompt.id for r in records if r.brands_mentioned & {c.name for c in workspace.competitors}})
    positions = [m.position for r in records for m in r.extraction.mentions if m.brand == target]

    def group(key):
        out: dict[str, dict[str, MetricValue]] = {}
        for k in sorted({key(r) for r in records}):
            sub = [r for r in records if key(r) == k]
            out[k] = {"mention_rate": mention_rate(sub, target), "citation_rate": citation_rate(sub, domain, target)}
            for c in workspace.competitors:
                out[k][f"mention_rate::{c.name}"] = mention_rate(sub, c.name)
        return out

    return RunMetrics(
        coverage=cov,
        mention_rate=mention_rate(records, target),
        citation_rate=citation_rate(records, domain, target),
        share_of_voice=share_of_voice(records, brands),
        competitor_gap_prompts=gaps,
        competitor_gap=_rate("Competitor gap", len(gaps), prompts_with_any_competitor, "Prompts where a competitor appears and the target does not / prompts with any competitor mention"),
        accuracy=acc,
        inaccurate_claims=conflicts,
        unverifiable_claims=unverifiable,
        sentiment_counts=sentiment_counts(records, target),
        by_provider=group(lambda r: r.response.provider),
        by_category=group(lambda r: r.prompt.category.value),
        absent_prompt_ids=absent_prompts(records, target),
        competitor_mention_rate={c.name: mention_rate(records, c.name) for c in workspace.competitors},
        competitor_citation_rate={c.name: citation_rate(records, c.domain, c.name) for c in workspace.competitors},
        avg_position=round(sum(positions) / len(positions), 2) if positions else None,
    )


def category_label(cat: str | PromptCategory) -> str:
    v = cat.value if isinstance(cat, PromptCategory) else cat
    return {"discovery": "Discovery", "comparison": "Comparison", "product_specific": "Product-specific",
            "problem_solving": "Problem-solving", "purchase_intent": "Purchase intent"}.get(v, v)
