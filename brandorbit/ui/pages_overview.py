from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.core.schemas import FindingStatus, Severity
from brandorbit.ui.common import (
    coverage_line, empty_state, get_repo, guard_run, hbar, insight_card, kpi, metric_kpi, numbered_list, page_header, previous_run,
    quote, run_metrics, section, select_workspace, short_pid, trend,
)

SEV_RANK = {Severity.high: 0, Severity.medium: 1, Severity.low: 2}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("Overview", f"{ws.brand.name} - {ws.brand.country}", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    m = run_metrics(repo, ws, run)
    prev = previous_run(repo, ws, run)
    pm = run_metrics(repo, ws, prev) if prev else None
    brand = ws.brand.name

    c = st.columns(4)
    with c[0]:
        metric_kpi("Brand mention rate", m.mention_rate, pm.mention_rate if pm else None, "Share of AI answers that mention the brand at all.")
    with c[1]:
        metric_kpi("Website cited", m.citation_rate, pm.citation_rate if pm else None, "Share of answers that cite the brand's own website as a source.")
    with c[2]:
        metric_kpi("Share of voice", m.share_of_voice[brand], pm.share_of_voice[brand] if pm else None, "Brand mentions as a share of all brand and competitor mentions.")
    with c[3]:
        kpi("Inaccurate claims", str(m.inaccurate_claims), help_text="Product facts in answers that conflict with the catalogue (price, warranty, specs).",
            sample=f"{m.accuracy.sample} verified", delta=(m.inaccurate_claims - pm.inaccurate_claims) if pm else None, invert=True)
    st.write("")
    coverage_line(m, prev.label if prev else None)

    left, right = st.columns([3, 2])
    with left:
        section("Visibility over time")
        runs = repo.list_runs(ws.id)
        if len(runs) < 2:
            empty_state("Trend needs at least two runs", "Run monitoring again to see how visibility moves between runs.")
        else:
            rows = []
            for r in runs:
                rm = run_metrics(repo, ws, r)
                for name, mv in (("Mention rate", rm.mention_rate), ("Website cited", rm.citation_rate), ("Share of voice", rm.share_of_voice[brand])):
                    rows.append({"run": r.started_at.strftime("%d %b"), "metric": name, "value": mv.value, "n": mv.sample, "label": r.label})
            trend(pd.DataFrame(rows), "run", "value", "metric", height=230, colors=["#1F6F5B", "#7C98AA", "#B9AE9A"])
    with right:
        section("Brand vs competitors", "mention rate")
        rows = [{"brand": brand, "mention rate": m.mention_rate.value or 0, "n": m.mention_rate.sample}]
        rows += [{"brand": c.name, "mention rate": m.competitor_mention_rate[c.name].value or 0, "n": m.competitor_mention_rate[c.name].sample} for c in ws.competitors]
        hbar(pd.DataFrame(rows), "brand", "mention rate", color="brand", domain=ws.all_brands(), height=230, sort=ws.all_brands())

    findings = [f for f in repo.list_findings(ws.id, run.id) if f.status in (FindingStatus.open, FindingStatus.planned)]
    findings.sort(key=lambda f: (SEV_RANK[f.severity], -f.confidence, f.finding_id))
    left, right = st.columns([3, 2])
    with left:
        section("Priority insight")
        if not findings:
            empty_state("No open issues", "Every finding for this run is completed or dismissed.")
        else:
            top = findings[0]
            insight_card(f"{top.severity.value} severity - {top.category.replace('_', ' ')}", top.title, top.explanation)
            ev = next((e for e in top.evidence if e.quote), None)
            if ev:
                quote(ev.quote, f"Prompt {short_pid(ev.prompt_id)} - response {ev.response_id}")
            st.markdown('<a href="recommendations" target="_self" style="font-size:.84rem;font-weight:600">Open recommendations &rarr;</a>', unsafe_allow_html=True)
    with right:
        section("Next actions")
        if findings:
            numbered_list([(f.title, f.proposed_action.split(". ")[0] + ".") for f in findings[:3]])
        else:
            empty_state("Nothing to do right now")
