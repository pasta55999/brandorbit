"""Before/after comparison of two monitoring runs over the same prompt set."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Optional

from brandorbit.core.metrics import AnswerRecord, RunMetrics, compute_run_metrics, join_records
from brandorbit.core.schemas import Finding, FindingStatus, Prompt, Workspace
from brandorbit.storage.repository import Repository

DISCLAIMER = ("Differences between runs do not establish causation. Changes may result from model variability, provider "
              "updates, search index changes or other factors unrelated to actions you took.")


@dataclass
class PairDelta:
    prompt_id: str
    prompt_text: str
    provider: str
    before_mentioned: Optional[bool]
    after_mentioned: Optional[bool]
    before_domains: list[str]
    after_domains: list[str]
    before_competitors: list[str]
    after_competitors: list[str]
    before_response_id: Optional[str]
    after_response_id: Optional[str]
    similarity: Optional[float]
    wording_changed: bool

    @property
    def change(self) -> str:
        if self.before_mentioned is None or self.after_mentioned is None:
            return "coverage differs"
        if not self.before_mentioned and self.after_mentioned:
            return "mention gained"
        if self.before_mentioned and not self.after_mentioned:
            return "mention lost"
        return "unchanged"


@dataclass
class RunComparison:
    before: RunMetrics
    after: RunMetrics
    pairs: list[PairDelta]
    gained: list[PairDelta]
    lost: list[PairDelta]
    coverage_mismatch: list[PairDelta]
    new_domains: list[str]
    dropped_domains: list[str]
    implemented_findings: list[Finding] = field(default_factory=list)
    common_prompt_ids: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def compare_runs(repo: Repository, workspace: Workspace, before_id: str, after_id: str) -> RunComparison:
    prompts = repo.list_prompts(workspace.id)
    pmap = {p.id: p for p in prompts}
    b_resp, a_resp = repo.list_responses(before_id), repo.list_responses(after_id)
    b_ext, a_ext = repo.list_extractions(before_id), repo.list_extractions(after_id)
    common = sorted({r.prompt_id for r in b_resp} & {r.prompt_id for r in a_resp})
    # restrict metrics to prompts present in both runs so coverage is comparable
    b_resp_c = [r for r in b_resp if r.prompt_id in common]
    a_resp_c = [r for r in a_resp if r.prompt_id in common]
    before = compute_run_metrics(workspace, prompts, b_resp_c, b_ext)
    after = compute_run_metrics(workspace, prompts, a_resp_c, a_ext)
    b_recs, _ = join_records(prompts, b_resp_c, b_ext)
    a_recs, _ = join_records(prompts, a_resp_c, a_ext)
    b_by = {(r.prompt.id, r.response.provider): r for r in b_recs}
    a_by = {(r.prompt.id, r.response.provider): r for r in a_recs}
    comps = {c.name for c in workspace.competitors}
    pairs: list[PairDelta] = []
    for key in sorted(set(b_by) | set(a_by)):
        b, a = b_by.get(key), a_by.get(key)
        sim = None
        if b and a:
            sim = round(difflib.SequenceMatcher(None, b.response.text, a.response.text).ratio(), 3)
        pairs.append(PairDelta(
            prompt_id=key[0], prompt_text=pmap[key[0]].text if key[0] in pmap else key[0], provider=key[1],
            before_mentioned=b.extraction.target_mentioned if b else None, after_mentioned=a.extraction.target_mentioned if a else None,
            before_domains=b.extraction.cited_domains if b else [], after_domains=a.extraction.cited_domains if a else [],
            before_competitors=sorted(b.brands_mentioned & comps) if b else [], after_competitors=sorted(a.brands_mentioned & comps) if a else [],
            before_response_id=b.response.id if b else None, after_response_id=a.response.id if a else None,
            similarity=sim, wording_changed=sim is not None and sim < 0.98,
        ))
    b_domains = {d for r in b_recs for d in r.extraction.cited_domains}
    a_domains = {d for r in a_recs for d in r.extraction.cited_domains}
    before_run, after_run = repo.get_run(before_id), repo.get_run(after_id)
    implemented = [f for f in repo.list_findings(workspace.id, before_id) if f.status == FindingStatus.completed] if before_run else []
    return RunComparison(
        before=before, after=after, pairs=pairs,
        gained=[p for p in pairs if p.change == "mention gained"], lost=[p for p in pairs if p.change == "mention lost"],
        coverage_mismatch=[p for p in pairs if p.change == "coverage differs"],
        new_domains=sorted(a_domains - b_domains), dropped_domains=sorted(b_domains - a_domains),
        implemented_findings=implemented, common_prompt_ids=common,
    )
