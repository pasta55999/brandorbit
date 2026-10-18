from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label, join_records
from brandorbit.ui.common import PALETTE, bar_chart, coverage_caption, demo_banner, get_repo, page_header, run_metrics, select_run, select_workspace, short_pid


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Visibility", "Where the brand appears - by provider, by prompt category, versus competitors, and over time.")
    demo_banner(ws, run)
    if run is None:
        st.info("No runs yet.")
        return
    m = run_metrics(repo, ws, run)
    coverage_caption(m)
    brands = ws.all_brands()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Mention rate by provider")
        rows = []
        for prov, d in m.by_provider.items():
            rows.append({"provider": prov, "brand": ws.brand.name, "rate": d["mention_rate"].value or 0, "n": d["mention_rate"].sample})
            for c in ws.competitors:
                mv = d[f"mention_rate::{c.name}"]
                rows.append({"provider": prov, "brand": c.name, "rate": mv.value or 0, "n": mv.sample})
        df = pd.DataFrame(rows)
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X("rate:Q", title="%", scale=alt.Scale(domain=[0, 100])), y=alt.Y("brand:N", title=None, sort=brands),
            color=alt.Color("brand:N", scale=alt.Scale(domain=brands, range=PALETTE), legend=None), row=alt.Row("provider:N", title=None),
            tooltip=["provider", "brand", "rate", "n"],
        ).properties(height=120)
        st.altair_chart(chart, use_container_width=True)
    with c2:
        st.markdown("#### Mention rate by prompt category")
        rows = []
        for cat, d in m.by_category.items():
            rows.append({"category": category_label(cat), "brand": ws.brand.name, "rate": d["mention_rate"].value or 0, "n": d["mention_rate"].sample})
            for c in ws.competitors:
                mv = d[f"mention_rate::{c.name}"]
                rows.append({"category": category_label(cat), "brand": c.name, "rate": mv.value or 0, "n": mv.sample})
        df = pd.DataFrame(rows)
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X("rate:Q", title="%", scale=alt.Scale(domain=[0, 100])), y=alt.Y("brand:N", title=None, sort=brands),
            color=alt.Color("brand:N", scale=alt.Scale(domain=brands, range=PALETTE), legend=alt.Legend(orient="bottom", title=None)),
            row=alt.Row("category:N", title=None), tooltip=["category", "brand", "rate", "n"],
        ).properties(height=120)
        st.altair_chart(chart, use_container_width=True)

    st.markdown("#### Brand versus competitors")
    rows = [{"brand": ws.brand.name, "mention rate": m.mention_rate.display, "mentions (n)": m.mention_rate.sample, "citation rate": m.citation_rate.display, "share of voice": m.share_of_voice[ws.brand.name].display, "avg. position": m.avg_position}]
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    for c in ws.competitors:
        pos = [x.position for r in records for x in r.extraction.mentions if x.brand == c.name]
        rows.append({"brand": c.name, "mention rate": m.competitor_mention_rate[c.name].display, "mentions (n)": m.competitor_mention_rate[c.name].sample,
                     "citation rate": m.competitor_citation_rate[c.name].display, "share of voice": m.share_of_voice[c.name].display,
                     "avg. position": round(sum(pos) / len(pos), 2) if pos else None})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("Mention rate, citation rate, share of voice and position measure different things - see docs/METRICS.md. Average position is the order of first appearance among detected brands (1 = first).")

    pmap = {p.id: p for p in prompts}
    t1, t2 = st.tabs(["Prompts where the brand is absent", "Competitor gaps (competitor present, brand absent)"])
    with t1:
        if m.absent_prompt_ids:
            st.dataframe(pd.DataFrame([{"id": short_pid(p), "category": category_label(pmap[p].category), "prompt": pmap[p].text} for p in m.absent_prompt_ids]), use_container_width=True, hide_index=True)
        else:
            st.success("No absent prompts in this run.")
    with t2:
        if m.competitor_gap_prompts:
            rows = []
            for pid in m.competitor_gap_prompts:
                comps = sorted({x.brand for r in records if r.prompt.id == pid for x in r.extraction.mentions if not x.is_target})
                rows.append({"id": short_pid(pid), "category": category_label(pmap[pid].category), "prompt": pmap[pid].text, "competitors mentioned": ", ".join(comps)})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.success("No competitor gaps in this run.")

    st.markdown("#### Historical trend")
    runs = repo.list_runs(ws.id)
    if len(runs) < 2:
        st.info("Run monitoring again to see trends across runs.")
    else:
        rows = []
        for r in runs:
            rm = run_metrics(repo, ws, r)
            for name, mv in (("Mention rate", rm.mention_rate), ("Citation rate", rm.citation_rate), ("Share of voice", rm.share_of_voice[ws.brand.name])):
                rows.append({"run": r.started_at.strftime("%Y-%m-%d"), "label": r.label, "metric": name, "value": mv.value, "n": mv.sample})
        df = pd.DataFrame(rows)
        chart = alt.Chart(df).mark_line(point=True).encode(
            x=alt.X("run:O", title=None), y=alt.Y("value:Q", title="%", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("metric:N", scale=alt.Scale(range=PALETTE), legend=alt.Legend(orient="bottom", title=None)), tooltip=["label", "metric", "value", "n"],
        ).properties(height=260)
        st.altair_chart(chart, use_container_width=True)
        st.caption("Differences between runs do not establish causation; model variability alone can move these numbers.")
