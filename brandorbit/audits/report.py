"""Markdown report for the product-data & website audit plus run findings."""

from __future__ import annotations

from datetime import datetime, timezone

from brandorbit.audits.catalogue_audit import AuditResult
from brandorbit.audits.website_audit import WebsiteAudit
from brandorbit.core.metrics import RunMetrics
from brandorbit.core.schemas import Finding, Workspace


def build_report(workspace: Workspace, audit: AuditResult, web: WebsiteAudit | None, metrics: RunMetrics | None, findings: list[Finding], demo: bool) -> str:
    lines = [f"# BrandOrbit audit report - {workspace.brand.name}", "",
             f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.",
             "**DEMO DATA**: this workspace uses fictional, hand-written fixtures. Nothing below is a real AI search result." if demo else
             "Results reflect the specific providers, models, prompts and time of the monitoring run; they are not a measurement of all consumer AI search experiences.",
             ""]
    if metrics:
        lines += ["## Visibility snapshot", "",
                  f"- Eligible answers: {metrics.coverage.eligible} of {metrics.coverage.responses_total} ({metrics.coverage.failed} failed/excluded)",
                  f"- Mention rate: {metrics.mention_rate.display} ({metrics.mention_rate.sample})",
                  f"- Website citation rate: {metrics.citation_rate.display} ({metrics.citation_rate.sample})",
                  f"- Brand accuracy rate: {metrics.accuracy.display} ({metrics.accuracy.sample}); conflicting claims: {metrics.inaccurate_claims}",
                  f"- Competitor-gap prompts: {len(metrics.competitor_gap_prompts)}", ""]
    sev = audit.by_severity()
    lines += ["## Product-data audit", "", f"Products checked: {audit.products_checked}. Issues: {sev['high']} high, {sev['medium']} medium, {sev['low']} low.", ""]
    if audit.attribute_coverage:
        lines += ["Attribute coverage: " + ", ".join(f"{k} {v:.0f}%" for k, v in audit.attribute_coverage.items()), ""]
    lines += ["| SKU | Check | Severity | Message |", "|---|---|---|---|"]
    lines += [f"| {i.sku} | {i.check} | {i.severity} | {i.message} |" for i in audit.issues]
    if web:
        lines += ["", f"## Website inspection ({web.source})", "", "| SKU | Check | Severity | Message |", "|---|---|---|---|"]
        lines += [f"| {i['sku']} | {i['check']} | {i['severity']} | {i['message']} |" for i in web.issues()] or ["| - | - | - | no issues |"]
    lines += ["", "## Findings & recommendations", ""]
    for f in findings:
        lines += [f"### {f.finding_id} - {f.title}", f"- Category: {f.category} | Severity: {f.severity.value} | Confidence: {f.confidence:.0%} | Verification: {f.verification_status.value} | Status: {f.status.value}",
                  f"- Why it matters: {f.explanation}", f"- Proposed action: {f.proposed_action}", f"- Expected outcome: {f.expected_outcome}",
                  f"- Limitations: {f.limitations}"]
        for e in f.evidence[:5]:
            q = f' "{e.quote}"' if e.quote else ""
            lines.append(f"  - Evidence: prompt `{e.prompt_id}` response `{e.response_id}`{q}" + (f" ({e.source_url})" if e.source_url else ""))
        lines.append("")
    lines += ["---", "Every recommendation is a hypothesis to test with a follow-up monitoring run. Differences between runs do not establish causation."]
    return "\n".join(lines)
