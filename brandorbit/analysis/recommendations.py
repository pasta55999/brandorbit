"""Findings and recommendations.

Findings are produced by deterministic rules over stored extractions, so every finding is
traceable to prompt/response ids and verbatim quotes. An optional LLM "narrator" can
rewrite the explanation/action text, but it is validated against ``LLMFindingNarrative``
and may only reuse quotes that already exist in the evidence - it can never add facts.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Optional

from pydantic import ValidationError

from brandorbit.analysis.extraction import BrandMatcher, sentences
from brandorbit.audits.catalogue_audit import audit_catalogue
from brandorbit.core.metrics import AnswerRecord, category_label, compute_run_metrics, join_records
from brandorbit.core.schemas import (
    Evidence,
    Finding,
    FindingStatus,
    LLMFindingNarrative,
    PromptCategory,
    Sentiment,
    Severity,
    VerificationStatus,
    Workspace,
)
from brandorbit.providers.base import Provider
from brandorbit.storage.repository import Repository, new_id

log = logging.getLogger(__name__)

CAUSATION_NOTE = "Visibility gaps are a hypothesis to test; a single missing attribute or page does not by itself cause poor AI visibility."


def _ev(r: AnswerRecord, quote: str = "", url: Optional[str] = None) -> Evidence:
    return Evidence(prompt_id=r.prompt.id, response_id=r.response.id, quote=quote[:400], source_url=url)


def _counter(prefix: str):
    n = 0

    def nxt() -> str:
        nonlocal n
        n += 1
        return f"F-{prefix}-{n:03d}"

    return nxt


def build_findings(workspace: Workspace, run_id: str, records: list[AnswerRecord], products, metrics) -> list[Finding]:
    target = workspace.brand.name
    comps = [c.name for c in workspace.competitors]
    findings: list[Finding] = []
    by_prompt: dict[str, list[AnswerRecord]] = defaultdict(list)
    for r in records:
        by_prompt[r.prompt.id].append(r)

    def mk(**kw) -> Finding:
        return Finding(id=new_id("fnd"), workspace_id=workspace.id, run_id=run_id, **kw)

    # ---- 1. Absent from discovery prompts ---------------------------------------
    gap_id = _counter("GAP")
    absent_disc = [pid for pid in metrics.absent_prompt_ids if by_prompt[pid][0].prompt.category == PromptCategory.discovery]
    if absent_disc:
        ev = [_ev(r, r.response.text[:200]) for pid in absent_disc for r in by_prompt[pid][:1]]
        n_disc = len({r.prompt.id for r in records if r.prompt.category == PromptCategory.discovery})
        findings.append(mk(
            finding_id=gap_id(), category="visibility_gap",
            severity=Severity.high if len(absent_disc) >= max(2, n_disc // 2) else Severity.medium,
            title=f"{target} is absent from {len(absent_disc)} of {n_disc} discovery prompts",
            explanation=(f"In this run, no eligible answer to {len(absent_disc)} discovery prompt(s) mentioned {target} at all, "
                         "while competitors were named. Discovery prompts are where shoppers without a brand in mind form their shortlist."),
            proposed_action=("Review how the brand and its categories are described on the website and in third-party coverage for these "
                             "queries. Consider publishing category-level buying guides and ensuring product pages state the category clearly."),
            expected_outcome="Hypothesis: clearer category coverage may increase the chance of being named in discovery answers in a future run.",
            evidence=ev, confidence=0.8, limitations=f"Based on {metrics.coverage.eligible} eligible answers from {len(metrics.coverage.providers)} simulated/live provider(s). " + CAUSATION_NOTE,
            verification_status=VerificationStatus.verified, related_prompt_ids=absent_disc,
        ))

    # ---- 2. Competitor repeatedly recommended for a need -------------------------
    need_counter: Counter = Counter()
    need_examples: dict[str, list[AnswerRecord]] = defaultdict(list)
    for pid in metrics.competitor_gap_prompts:
        for r in by_prompt[pid]:
            for m in r.extraction.mentions:
                if m.brand in comps and m.recommended:
                    need_counter[(pid, m.brand)] += 1
                    need_examples[(pid, m.brand)].append(r)
    comp_totals = Counter()
    for (pid, brand), n in need_counter.items():
        comp_totals[brand] += 1
    for brand, n_prompts in comp_totals.most_common(2):
        if n_prompts < 2:
            continue
        pids = sorted({pid for (pid, b) in need_counter if b == brand})
        ev = []
        for pid in pids:
            r = need_examples[(pid, brand)][0]
            m = next(x for x in r.extraction.mentions if x.brand == brand)
            ev.append(_ev(r, m.evidence_quote))
        findings.append(mk(
            finding_id=gap_id(), category="competitor_gap", severity=Severity.high if n_prompts >= 3 else Severity.medium,
            title=f"{brand} is recommended in {n_prompts} prompts where {target} is missing",
            explanation=f"{brand} appears with recommendation language in answers to {n_prompts} prompt(s) ({', '.join(category_label(by_prompt[p][0].prompt.category) for p in pids)}) where {target} is never mentioned.",
            proposed_action=f"Study what {brand} communicates for these needs (warranty, runtime, pet features, etc.) and verify the equivalent {target} product information is explicit on its product pages and in supplied catalogue data.",
            expected_outcome="Hypothesis: making the matching product attributes explicit may let answers position the brand alongside the competitor for these needs.",
            evidence=ev, confidence=0.75, limitations=CAUSATION_NOTE, verification_status=VerificationStatus.verified, related_prompt_ids=pids,
        ))

    # ---- 3. Inaccurate claims --------------------------------------------------
    acc_id = _counter("ACC")
    conflicts: dict[tuple, list[tuple[AnswerRecord, object]]] = defaultdict(list)
    for r in records:
        for c in r.extraction.claims:
            if c.verification_status == VerificationStatus.conflict:
                conflicts[(c.attribute, c.product or target)].append((r, c))
    for (attribute, product), items in sorted(conflicts.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        ev = [_ev(r, c.quote, next((u.url for u in r.response.citations), None)) for r, c in items]
        claimed = sorted({c.claimed_value for _, c in items})
        trusted = items[0][1].trusted_value
        findings.append(mk(
            finding_id=acc_id(), category="inaccurate_claim", severity=Severity.high if attribute in {"price", "warranty"} else Severity.medium,
            title=f"Answers state a {attribute} for {product} that conflicts with catalogue data",
            explanation=f"{len(items)} answer(s) give {attribute} = {', '.join(claimed)}, whereas the supplied catalogue says {trusted}. Shoppers may be misled or deterred by the wrong figure.",
            proposed_action="Confirm the catalogue value is current, then check the cited sources and the brand's own pages for the outdated figure. If a third-party page is the origin, request a correction; ensure structured data on the product page carries the right value.",
            expected_outcome="Hypothesis: once public sources agree, later answers are more likely to repeat the correct figure. Model outputs remain variable.",
            evidence=ev, source_url=next((e.source_url for e in ev if e.source_url), None), confidence=0.85,
            limitations="Verification compares against the user-supplied catalogue, which may itself be outdated.",
            verification_status=VerificationStatus.conflict, related_prompt_ids=sorted({r.prompt.id for r, _ in items}),
        ))

    # ---- 4. Website rarely cited even when mentioned ---------------------------
    cit_id = _counter("CIT")
    mentioned = [r for r in records if r.extraction.target_mentioned]
    if mentioned:
        cited = [r for r in mentioned if r.extraction.target_cited]
        uncited = [r for r in mentioned if not r.extraction.target_cited and r.extraction.cited_domains]
        if uncited and len(cited) / len(mentioned) < 0.6:
            third = Counter(d for r in uncited for d in r.extraction.cited_domains)
            findings.append(mk(
                finding_id=cit_id(), category="citation_gap", severity=Severity.medium,
                title=f"{workspace.brand.domain} is cited in only {len(cited)} of {len(mentioned)} answers that mention {target}",
                explanation=f"When {target} is mentioned, answers often cite third-party pages ({', '.join(d for d, _ in third.most_common(3))}) instead of the brand's own site. Third-party pages control the narrative and can go stale.",
                proposed_action="Make sure key product and policy pages (warranty, delivery, specifications) are crawlable, clearly titled and contain the facts shoppers ask about, so they can be used as sources.",
                expected_outcome="Hypothesis: authoritative first-party pages may be cited more often for brand-related questions.",
                evidence=[_ev(r, "", r.response.citations[0].url if r.response.citations else None) for r in uncited[:5]],
                confidence=0.6, limitations="Citation behaviour varies strongly by provider; providers without search return no citations at all.",
                verification_status=VerificationStatus.verified, related_prompt_ids=sorted({r.prompt.id for r in uncited}),
            ))

    # ---- 5. Outdated / conflicting third-party source --------------------------
    src_id = _counter("SRC")
    stale_cues = ["only ships within", "only ships in", "1-year warranty", "discontinued"]
    stale: dict[str, list[tuple[AnswerRecord, str]]] = defaultdict(list)
    own_domains = {workspace.brand.domain} | {c.domain for c in workspace.competitors}
    target_pat = BrandMatcher(workspace).patterns[target]
    for r in mentioned:
        third_party = [c for c in r.response.citations if c.domain and c.domain not in own_domains]
        if not third_party:
            continue
        for sent in sentences(r.response.text):
            if target_pat.search(sent) and any(cue in sent.lower() for cue in stale_cues):
                stale[third_party[0].domain].append((r, sent))
    for domain, items in sorted(stale.items()):
        uniq = {(r.response.id, q): (r, q) for r, q in items}
        findings.append(mk(
            finding_id=src_id(), category="source_quality", severity=Severity.medium,
            title=f"Answers citing {domain} contain statements about {target} that look outdated",
            explanation=f"{len(uniq)} answer(s) that cite {domain} include statements about {target} that conflict with the configured brand profile (e.g. delivery coverage or warranty length).",
            proposed_action=f"Review the cited {domain} page(s), verify what they say about {target}, and request an update if the information is outdated.",
            expected_outcome="Hypothesis: correcting a frequently cited source may reduce repetition of the outdated statement.",
            evidence=[_ev(r, q, next((c.url for c in r.response.citations if c.domain == domain), None)) for r, q in uniq.values()],
            source_url=next((c.url for r, _ in uniq.values() for c in r.response.citations if c.domain == domain), None),
            confidence=0.55, limitations="Detected with keyword cues; the page content itself was not fetched in demo mode, so this is unverified.",
            verification_status=VerificationStatus.unverifiable, related_prompt_ids=sorted({r.prompt.id for r, _ in uniq.values()}),
        ))

    # ---- 6. Negative / uncertain perception ---------------------------------------
    per_id = _counter("PER")
    negatives = [(r, m) for r in records for m in r.extraction.mentions if m.brand == target and m.sentiment in (Sentiment.negative, Sentiment.uncertain)]
    if negatives:
        findings.append(mk(
            finding_id=per_id(), category="perception", severity=Severity.medium if any(m.sentiment == Sentiment.negative for _, m in negatives) else Severity.low,
            title=f"{len(negatives)} answer(s) describe {target} with negative or hedged language",
            explanation="These answers attach concerns (e.g. battery degradation, shorter warranty) to the brand. Even hedged statements shape perception when repeated across answers.",
            proposed_action="Check whether the concern is factual. If it is, address it in product content; if it is not, identify the source and publish clear, verifiable counter-information.",
            expected_outcome="Hypothesis: addressing the underlying concern may shift sentiment labels in later runs. Sentiment classification here is lexicon-based and should be reviewed by a human.",
            evidence=[_ev(r, m.evidence_quote) for r, m in negatives], confidence=0.55,
            limitations="Lexicon-based sentiment; hedged statements are labelled uncertain rather than negative.",
            verification_status=VerificationStatus.inconclusive, related_prompt_ids=sorted({r.prompt.id for r, _ in negatives}),
        ))

    # ---- 7. Catalogue gaps linked to monitored needs ----------------------------
    cat_id = _counter("CAT")
    audit = audit_catalogue(products, workspace)
    severe = [i for i in audit.issues if i.severity in ("high", "medium")]
    if severe:
        attr_issues = [i for i in severe if i.check in ("missing_attribute", "missing_description")]
        # link to prompts whose wording touches the missing attribute
        linked: list[str] = []
        for pid, recs in by_prompt.items():
            txt = recs[0].prompt.text.lower()
            if any(k in txt for k in ("quiet", "warranty", "runtime", "watt", "power", "capacity", "price")):
                linked.append(pid)
        findings.append(mk(
            finding_id=cat_id(), category="catalogue_gap", severity=Severity.medium,
            title=f"Catalogue has {len(attr_issues)} missing attribute/description issues across {len({i.sku for i in attr_issues})} products",
            explanation="Products with missing wattage, descriptions or inconsistent names give AI systems and shoppers less to work with. "
                        + "; ".join(f"{i.sku}: {i.message}" for i in attr_issues[:4]) + (" ..." if len(attr_issues) > 4 else ""),
            proposed_action="Complete the missing fields in the catalogue and on the product pages. Prioritise attributes that monitored prompts ask about (noise level, warranty, runtime, power).",
            expected_outcome="Hypothesis: richer, consistent product data gives answer engines explicit facts to cite. This is an input improvement, not a guaranteed visibility change.",
            evidence=[_ev(by_prompt[pid][0]) for pid in sorted(linked)[:4]], confidence=0.7,
            limitations="Derived from the uploaded catalogue only. " + CAUSATION_NOTE,
            verification_status=VerificationStatus.verified, related_prompt_ids=sorted(linked),
        ))
    return findings


def generate_findings(repo: Repository, workspace: Workspace, run_id: str, narrator: Optional[Provider] = None) -> list[Finding]:
    prompts = repo.list_prompts(workspace.id)
    responses = repo.list_responses(run_id)
    extractions = repo.list_extractions(run_id)
    records, _ = join_records(prompts, responses, extractions)
    metrics = compute_run_metrics(workspace, prompts, responses, extractions)
    products = repo.list_products(workspace.id)
    previous = {f.finding_id: f.status for f in repo.list_findings(workspace.id, run_id)}
    findings = build_findings(workspace, run_id, records, products, metrics)
    if narrator is not None:
        findings = [narrate(f, narrator) for f in findings]
    repo.delete_findings_for_run(run_id)
    for f in findings:
        if f.finding_id in previous:
            f.status = previous[f.finding_id]
        repo.save_finding(f)
    return findings


NARRATOR_SYSTEM = (
    "You rewrite a brand-visibility finding for a marketing operator. Use only the facts in the JSON provided; "
    "do not add numbers, quotes, URLs or product facts that are not present. Return JSON with keys: finding_id, "
    "explanation, proposed_action, expected_outcome (phrased as a hypothesis), confidence (0-1), quotes_used (list of quotes copied verbatim)."
)


def narrate(finding: Finding, provider: Provider) -> Finding:
    """LLM enrichment with strict validation; falls back to the rule text on any problem."""
    payload = finding.model_dump(mode="json", include={"finding_id", "title", "explanation", "proposed_action", "evidence", "limitations"})
    raw = provider.structured(NARRATOR_SYSTEM, json.dumps(payload), "LLMFindingNarrative")
    if not raw:
        return finding
    try:
        out = LLMFindingNarrative.model_validate_json(raw)
    except ValidationError as exc:
        log.warning("narrator output rejected: %s", exc)
        return finding
    allowed = {e.quote for e in finding.evidence}
    if out.finding_id != finding.finding_id or any(q not in allowed for q in out.quotes_used):
        log.warning("narrator for %s used quotes not in evidence; discarded", finding.finding_id)
        return finding
    return finding.model_copy(update={
        "explanation": out.explanation, "proposed_action": out.proposed_action, "expected_outcome": out.expected_outcome,
        "confidence": min(finding.confidence, out.confidence), "generated_by": "rules+llm",
    })


def status_options() -> list[str]:
    return [s.value for s in FindingStatus]
