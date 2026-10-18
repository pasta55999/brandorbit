from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from brandorbit.analysis.comparison import compare_runs
from brandorbit.analysis.recommendations import generate_findings
from brandorbit.core.metrics import compute_run_metrics
from brandorbit.core.schemas import (
    BrandProfile, Citation, Competitor, Extraction, Finding, FindingStatus, LLMExtractionOutput, Mention, Prompt, PromptCategory,
    RawResponse, ResponseStatus, Workspace, normalise_url,
)
from brandorbit.monitoring.demo_loader import DEMO_WORKSPACE_ID
from brandorbit.monitoring.runner import RunLimitError, run_monitoring
from brandorbit.providers.base import Provider, ProviderResult
from brandorbit.storage.repository import Repository


# ------------------------------------------------------------------ schemas
def test_url_normalisation_and_validation():
    assert normalise_url("example.ae") == "https://example.ae"
    assert normalise_url("https://www.example.ae/") == "https://www.example.ae"
    with pytest.raises(ValueError):
        normalise_url("not a url")
    with pytest.raises(ValidationError):
        BrandProfile(name="X", website="ftp://x", industry="y")


def test_workspace_rejects_duplicate_names():
    with pytest.raises(ValidationError):
        Workspace(id="w", name="w", brand=BrandProfile(name="A", website="a.com", industry="i"), competitors=[Competitor(name="a")])


def test_llm_output_schema_requires_quotes():
    with pytest.raises(ValidationError):
        LLMExtractionOutput(mentions=[Mention(brand="A", is_target=True, position=1, evidence_quote="")], overall_confidence=0.9)
    with pytest.raises(ValidationError):
        LLMExtractionOutput.model_validate_json('{"mentions": "oops"}')


def test_finding_id_pattern():
    base = dict(id="x", workspace_id="w", run_id="r", category="visibility_gap", severity="high", title="t", explanation="e",
                proposed_action="a", expected_outcome="h", confidence=0.5)
    Finding(finding_id="F-GAP-001", **base)
    with pytest.raises(ValidationError):
        Finding(finding_id="GAP1", **base)


# ------------------------------------------------------------------ metrics
def _mk(ws, prompts, specs):
    """specs: list of (prompt_id, status, brands, domains, provider)."""
    responses, extractions = [], []
    for i, (pid, status, brands, domains, prov) in enumerate(specs):
        r = RawResponse(id=f"r{i}", run_id="run", prompt_id=pid, provider=prov, model="m", text="x" if status == "ok" else "", status=ResponseStatus(status))
        responses.append(r)
        extractions.append(Extraction(id=f"e{i}", response_id=r.id, mentions=[Mention(brand=b, is_target=b == ws.brand.name, position=k + 1, evidence_quote="x") for k, b in enumerate(brands)],
                                      cited_domains=domains, target_mentioned=ws.brand.name in brands, target_cited=ws.brand.domain in domains))
    return responses, extractions


def test_metric_definitions_and_failed_runs_excluded(ws):
    prompts = [Prompt(id=p, workspace_id=ws.id, text="some long prompt text", category=PromptCategory.discovery) for p in ("p1", "p2", "p3")]
    specs = [
        ("p1", "ok", ["Seraj Home", "HomeNest UAE"], ["serajhome.ae"], "a"),
        ("p2", "ok", ["HomeNest UAE"], ["homenest.ae"], "a"),
        ("p3", "ok", [], [], "a"),
        ("p3", "timeout", [], [], "b"),
    ]
    m = compute_run_metrics(ws, prompts, *_mk(ws, prompts, specs))
    assert m.coverage.eligible == 3 and m.coverage.failed == 1
    assert m.mention_rate.sample == "1/3" and m.mention_rate.value == pytest.approx(33.3)
    assert m.citation_rate.sample == "1/3"
    assert m.share_of_voice["Seraj Home"].sample == "1/3"  # 1 of 3 detected brand mentions
    assert m.share_of_voice["HomeNest UAE"].sample == "2/3"
    assert m.competitor_gap_prompts == ["p2"] and m.competitor_gap.sample == "1/2"
    assert m.absent_prompt_ids == ["p2", "p3"]


def test_metrics_with_no_eligible_answers_are_na(ws):
    prompts = [Prompt(id="p1", workspace_id=ws.id, text="some long prompt text", category=PromptCategory.discovery)]
    m = compute_run_metrics(ws, prompts, *_mk(ws, prompts, [("p1", "error", [], [], "a")]))
    assert m.mention_rate.value is None and m.mention_rate.display == "n/a"


# ------------------------------------------------------------------ storage
def test_raw_responses_are_append_only(repo):
    r = RawResponse(id="r1", run_id="run", prompt_id="p", provider="a", model="m", text="hello")
    repo.add_response(r)
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_response(r)
    assert repo.get_response("r1").text == "hello"


def test_demo_workspace_persists_and_reloads(demo_repo):
    counts = demo_repo.counts()
    assert counts["workspaces"] == 1 and counts["prompts"] == 16 and counts["runs"] == 2 and counts["responses"] == 64
    ws = demo_repo.get_workspace(DEMO_WORKSPACE_ID)
    assert ws.is_demo and ws.brand.domain == "serajhome.ae"
    runs = demo_repo.list_runs(ws.id)
    assert runs[0].is_baseline and runs[1].status == "partial"
    assert all(r.source_kind.value == "demo_fixture" for r in demo_repo.list_responses(runs[0].id))


def test_finding_status_roundtrip(demo_repo):
    ws = demo_repo.get_workspace(DEMO_WORKSPACE_ID)
    f = demo_repo.list_findings(ws.id)[0]
    demo_repo.update_finding_status(f.id, FindingStatus.planned)
    assert demo_repo.get_finding(f.id).status == FindingStatus.planned
    # regenerating findings keeps the user's status for the same finding id
    generate_findings(demo_repo, ws, f.run_id)
    again = next(x for x in demo_repo.list_findings(ws.id, f.run_id) if x.finding_id == f.finding_id)
    assert again.status == FindingStatus.planned


# ------------------------------------------------------------- recommendations
def test_findings_are_grounded_in_stored_evidence(demo_repo):
    ws = demo_repo.get_workspace(DEMO_WORKSPACE_ID)
    findings = demo_repo.list_findings(ws.id)
    assert findings
    for f in findings:
        assert f.evidence, f.finding_id
        for e in f.evidence:
            r = demo_repo.get_response(e.response_id)
            assert r is not None and r.prompt_id == e.prompt_id
            if e.quote:
                assert e.quote in r.text, (f.finding_id, e.quote)
            if e.source_url:
                assert any(c.url == e.source_url for c in r.citations)
        assert "hypothes" in f.expected_outcome.lower()


def test_demo_findings_cover_expected_categories(demo_repo):
    ws = demo_repo.get_workspace(DEMO_WORKSPACE_ID)
    cats = {f.category for f in demo_repo.list_findings(ws.id, "run_demo_baseline")}
    assert {"visibility_gap", "competitor_gap", "inaccurate_claim", "citation_gap", "source_quality", "perception", "catalogue_gap"} <= cats


# ------------------------------------------------------------------- runner
class FlakyProvider(Provider):
    id = "flaky"
    model = "flaky-1"

    def __init__(self):
        self.calls = 0

    def answer(self, prompt_text, **kw):
        self.calls += 1
        if self.calls % 2 == 0:
            return ProviderResult(status=ResponseStatus.timeout, error="boom", model=self.model)
        return ProviderResult(text="Seraj Home is great. HomeNest UAE too.", citations=[Citation(url="https://www.serajhome.ae/")], latency_ms=5, model=self.model)


def test_partial_run_is_recorded_and_metrics_exclude_failures(repo, ws, products):
    repo.save_workspace(ws)
    repo.replace_products(ws.id, products)
    prompts = [Prompt(id=f"p{i}", workspace_id=ws.id, text=f"prompt number {i} about appliances", category=PromptCategory.discovery) for i in range(4)]
    repo.save_prompts(prompts)
    run = run_monitoring(repo, ws, [FlakyProvider()], label="t")
    assert run.status == "partial"
    responses = repo.list_responses(run.id)
    assert len(responses) == 4 and sum(r.status == ResponseStatus.ok for r in responses) == 2
    m = compute_run_metrics(ws, prompts, responses, repo.list_extractions(run.id))
    assert m.coverage.failed == 2 and m.mention_rate.sample == "2/2"
    assert len(repo.list_provider_logs(run.id)) == 4


def test_run_limits_enforced(repo, ws):
    repo.save_workspace(ws)
    repo.save_prompts([Prompt(id=f"p{i}", workspace_id=ws.id, text=f"prompt number {i} about appliances", category=PromptCategory.discovery) for i in range(30)])
    with pytest.raises(RunLimitError):
        run_monitoring(repo, ws, [FlakyProvider()])


def test_demo_provider_never_invents_answers(repo, ws):
    from brandorbit.providers.demo import DemoProvider

    out = DemoProvider("demo-alpha").answer("brand new prompt", prompt_id="nope", run_id="r", country="UAE", currency="AED")
    assert out.status == ResponseStatus.error and out.text == "" and "never fabricates" in out.error


# --------------------------------------------------------------- comparison
def test_before_after_comparison(demo_repo):
    ws = demo_repo.get_workspace(DEMO_WORKSPACE_ID)
    cmp = compare_runs(demo_repo, ws, "run_demo_baseline", "run_demo_followup")
    assert len(cmp.common_prompt_ids) == 16
    assert {(p.prompt_id.split(":")[-1], p.provider) for p in cmp.gained} == {("p01", "demo-beta"), ("p03", "demo-beta"), ("p09", "demo-beta"), ("p11", "demo-alpha")}
    assert {(p.prompt_id.split(":")[-1], p.provider) for p in cmp.lost} == {("p02", "demo-alpha")}
    assert len(cmp.coverage_mismatch) == 2  # one timeout, one malformed answer in the follow-up
    assert cmp.after.mention_rate.value > cmp.before.mention_rate.value
    assert cmp.before.inaccurate_claims == 4 and cmp.after.inaccurate_claims == 0
    assert {f.finding_id for f in cmp.implemented_findings} == {"F-ACC-001", "F-ACC-003", "F-GAP-002", "F-CAT-001"}
    assert "causation" in cmp.disclaimer
