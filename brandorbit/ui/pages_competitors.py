from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label, join_records
from brandorbit.ui.common import bar_chart, coverage_caption, demo_banner, get_repo, page_header, run_metrics, select_run, select_workspace, short_pid

DEFINITIONS = {
    "Mention rate": "Percentage of eligible answers in which the brand is mentioned (at least one alias match).",
    "Citation rate": "Percentage of eligible answers that cite the brand's website domain (provider citations or inline URLs).",
    "Share of voice": "Brand mentions / all detected brand mentions across the selected answers (max one per brand per answer).",
    "Competitor gap": "Prompts where at least one competitor appears in some eligible answer and the target brand appears in none.",
    "Brand accuracy rate": "Verified claims / (verified + conflicting) claims about the target brand, checked against the supplied catalogue. Unverifiable claims are excluded.",
    "Eligible answer": "A stored response with status ok and non-empty text. Failed, timed-out or malformed responses are excluded from denominators and reported as coverage gaps.",
}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Competitors", "Side-by-side comparison across the same prompts and run. Sample sizes are shown for every number.")
    demo_banner(ws, run)
    if run is None:
        st.info("No runs yet.")
        return
    m = run_metrics(repo, ws, run)
    coverage_caption(m)
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))

    rows = []
    for b in ws.all_brands():
        is_t = b == ws.brand.name
        mr = m.mention_rate if is_t else m.competitor_mention_rate[b]
        cr = m.citation_rate if is_t else m.competitor_citation_rate[b]
        rec = sum(1 for r in records for x in r.extraction.mentions if x.brand == b and x.recommended)
        first = sum(1 for r in records for x in r.extraction.mentions if x.brand == b and x.position == 1)
        rows.append({"brand": ("* " if is_t else "") + b, "mention rate": mr.value, "mentions n": mr.sample, "citation rate": cr.value, "citations n": cr.sample,
                     "share of voice": m.share_of_voice[b].value, "recommended (answers)": rec, "mentioned first (answers)": first})
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, column_config={
        "mention rate": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
        "citation rate": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
        "share of voice": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100),
    })
    st.caption("* target brand. 'Recommended' counts answers where the brand's sentences contain recommendation language; it is distinct from being mentioned.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Share of voice by prompt category")
        rows = []
        for cat in sorted({r.prompt.category.value for r in records}):
            sub = [r for r in records if r.prompt.category.value == cat]
            cnt = Counter(b for r in sub for b in r.brands_mentioned)
            tot = sum(cnt.values()) or 1
            for b in ws.all_brands():
                rows.append({"category": category_label(cat), "brand": b, "share": round(100 * cnt[b] / tot, 1), "n": f"{cnt[b]}/{tot}"})
        df = pd.DataFrame(rows)
        import altair as alt
        from brandorbit.ui.common import PALETTE
        chart = alt.Chart(df).mark_bar().encode(
            x=alt.X("share:Q", stack="normalize", title="share of detected mentions", axis=alt.Axis(format="%")), y=alt.Y("category:N", title=None),
            color=alt.Color("brand:N", scale=alt.Scale(domain=ws.all_brands(), range=PALETTE), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["category", "brand", "share", "n"],
        ).properties(height=220)
        st.altair_chart(chart, use_container_width=True)
    with c2:
        st.markdown("#### Competitor gap prompts")
        pmap = {p.id: p for p in prompts}
        if m.competitor_gap_prompts:
            rows = []
            for pid in m.competitor_gap_prompts:
                comps = Counter(x.brand for r in records if r.prompt.id == pid for x in r.extraction.mentions if not x.is_target)
                rows.append({"id": short_pid(pid), "prompt": pmap[pid].text, "competitors": ", ".join(f"{b} ({n})" for b, n in comps.most_common())})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.success("No competitor gaps.")
        st.metric("Competitor gap", f"{len(m.competitor_gap_prompts)} prompts", help=m.competitor_gap.definition + f" (n = {m.competitor_gap.sample})")

    st.markdown("#### Head-to-head: prompts where each competitor appears without the brand")
    rows = []
    for c in ws.competitors:
        pids = sorted({r.prompt.id for r in records if c.name in r.brands_mentioned and ws.brand.name not in r.brands_mentioned})
        both = sorted({r.prompt.id for r in records if c.name in r.brands_mentioned and ws.brand.name in r.brands_mentioned})
        rows.append({"competitor": c.name, "answers with competitor only": len(pids), "answers with both": len(both), "example prompts": ", ".join(short_pid(p) for p in pids[:6])})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with st.expander("Metric definitions and treatment of missing data"):
        for k, v in DEFINITIONS.items():
            st.markdown(f"**{k}** - {v}")
        st.markdown("Metrics from runs with different coverage (e.g. a partial run with failed calls) are flagged in the coverage line above; compare like with like.")
