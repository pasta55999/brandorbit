from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label
from brandorbit.ui.common import (
    bar_chart, coverage_caption, demo_banner, get_repo, metric_card, metric_sub, page_header, run_metrics, select_run, select_workspace, short_pid,
)


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Overview", f"{ws.brand.name} - {ws.brand.industry} - {ws.brand.country} ({ws.brand.currency})")
    demo_banner(ws, run)
    if run is None:
        st.info("No monitoring runs yet. Go to **Settings** to approve prompts and run monitoring (demo providers work without an API key).")
        return
    m = run_metrics(repo, ws, run)
    runs = repo.list_runs(ws.id)
    prev = None
    idx = [r.id for r in runs].index(run.id)
    if idx > 0:
        prev = run_metrics(repo, ws, runs[idx - 1])

    def delta(cur, before):
        return None if (before is None or cur.value is None or before.value is None) else round(cur.value - before.value, 1)

    sov = m.share_of_voice[ws.brand.name]
    comp_sov = 100 - (sov.value or 0) if sov.value is not None else None
    c = st.columns(6)
    with c[0]:
        metric_card("Prompts monitored", str(m.coverage.prompts), f"{m.coverage.eligible} eligible answers, {len(m.coverage.providers)} provider(s)")
    with c[1]:
        metric_card("Brand mention rate", m.mention_rate.display, metric_sub(m.mention_rate), delta(m.mention_rate, prev.mention_rate if prev else None))
    with c[2]:
        metric_card("Website citation rate", m.citation_rate.display, metric_sub(m.citation_rate), delta(m.citation_rate, prev.citation_rate if prev else None))
    with c[3]:
        metric_card("Competitor share of voice", "n/a" if comp_sov is None else f"{comp_sov:.1f}%", f"Brand SoV {sov.display} (n = {sov.sample})",
                    None if (prev is None or comp_sov is None or prev.share_of_voice[ws.brand.name].value is None) else round(-(sov.value - prev.share_of_voice[ws.brand.name].value), 1))
    with c[4]:
        metric_card("Potentially inaccurate claims", str(m.inaccurate_claims), f"Accuracy {m.accuracy.display} (n = {m.accuracy.sample}); {m.unverifiable_claims} unverifiable")
    with c[5]:
        metric_card("Competitor-gap prompts", str(len(m.competitor_gap_prompts)), metric_sub(m.competitor_gap))
    st.write("")
    coverage_caption(m)
    if prev:
        st.caption(f"Deltas compare with the previous run ({runs[idx - 1].label}). Differences between runs do not establish causation.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Mention rate by prompt category")
        rows = [{"category": category_label(k), "rate": v["mention_rate"].value or 0, "n": v["mention_rate"].sample} for k, v in m.by_category.items()]
        bar_chart(pd.DataFrame(rows), "category", "rate")
    with right:
        st.markdown("#### Share of voice")
        rows = [{"brand": b, "share": v.value or 0, "n": v.sample} for b, v in m.share_of_voice.items()]
        bar_chart(pd.DataFrame(rows), "brand", "share")

    st.markdown("#### Visibility across runs")
    hist = []
    for r in runs:
        rm = run_metrics(repo, ws, r)
        hist.append({"run": r.label, "started": r.started_at.strftime("%Y-%m-%d"), "status": r.status, "eligible answers": rm.coverage.eligible,
                     "mention rate": rm.mention_rate.display, "citation rate": rm.citation_rate.display, "brand SoV": rm.share_of_voice[ws.brand.name].display,
                     "inaccurate claims": rm.inaccurate_claims, "competitor gaps": len(rm.competitor_gap_prompts)})
    st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)

    st.markdown("#### Prompts where the brand is absent")
    pmap = {p.id: p for p in repo.list_prompts(ws.id)}
    if m.absent_prompt_ids:
        st.dataframe(pd.DataFrame([{"id": short_pid(pid), "category": category_label(pmap[pid].category), "prompt": pmap[pid].text,
                                    "competitor gap": "yes" if pid in m.competitor_gap_prompts else "no"} for pid in m.absent_prompt_ids]),
                     use_container_width=True, hide_index=True)
    else:
        st.success("The brand was mentioned in at least one eligible answer for every prompt in this run.")
