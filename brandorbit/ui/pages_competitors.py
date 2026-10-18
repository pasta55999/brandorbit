from __future__ import annotations

from collections import Counter

import altair as alt
import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label, join_records
from brandorbit.ui.common import (
    chart, chip, coverage_line, df_table, empty_state, get_repo, guard_run, page_header, pct_col, quote, run_metrics, section, select_workspace, short_pid, source_tag,
)
from brandorbit.ui.theme import BRAND_SERIES


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("Competitors", "Who AI answers name instead of you, and for which customer needs.", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    m = run_metrics(repo, ws, run)
    brand = ws.brand.name
    brands = ws.all_brands()
    prompts = repo.list_prompts(ws.id)
    pmap = {p.id: p for p in prompts}
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    coverage_line(m)

    section("Comparison", "same prompts, same run")
    rows = []
    for b in brands:
        is_t = b == brand
        mr = m.mention_rate if is_t else m.competitor_mention_rate[b]
        cr = m.citation_rate if is_t else m.competitor_citation_rate[b]
        rec = sum(1 for r in records for x in r.extraction.mentions if x.brand == b and x.recommended)
        first = sum(1 for r in records for x in r.extraction.mentions if x.brand == b and x.position == 1)
        rows.append({"brand": ("You - " if is_t else "") + b, "mention rate": mr.value or 0, "website cited": cr.value or 0, "share of voice": m.share_of_voice[b].value or 0,
                     "recommended": rec, "named first": first, "n": mr.sample})
    df_table(pd.DataFrame(rows), column_config={
        "mention rate": pct_col("Mention rate", help="Eligible answers mentioning the brand"),
        "website cited": pct_col("Website cited", help="Eligible answers citing the brand's domain"),
        "share of voice": pct_col("Share of voice", help="Brand mentions / all brand mentions"),
        "recommended": st.column_config.NumberColumn("Recommended", help="Answers whose sentences about the brand use recommendation language"),
        "named first": st.column_config.NumberColumn("Named first", help="Answers where the brand is the first brand mentioned"),
        "n": st.column_config.TextColumn("n", help="Mentions / eligible answers"),
    })

    left, right = st.columns([3, 2])
    with left:
        section("Share of voice by intent")
        rows = []
        for cat in sorted({r.prompt.category.value for r in records}):
            sub = [r for r in records if r.prompt.category.value == cat]
            cnt = Counter(b for r in sub for b in r.brands_mentioned)
            tot = sum(cnt.values()) or 1
            rows += [{"intent": category_label(cat), "brand": b, "share": round(100 * cnt[b] / tot, 1), "mentions": cnt[b], "order": i} for i, b in enumerate(brands)]
        c = alt.Chart(pd.DataFrame(rows)).mark_bar(size=18).encode(
            x=alt.X("share:Q", stack="normalize", title=None, axis=alt.Axis(format="%")), y=alt.Y("intent:N", title=None),
            color=alt.Color("brand:N", scale=alt.Scale(domain=brands, range=BRAND_SERIES), legend=alt.Legend(orient="bottom", columns=3)),
            order=alt.Order("order:Q"), tooltip=["intent", "brand", "share", "mentions"],
        ).properties(height=200)
        chart(c)
    with right:
        section("Where you lose", "competitor named, brand absent")
        gaps = m.competitor_gap_prompts
        if not gaps:
            st.markdown(chip("No competitor gaps in this run", "good"), unsafe_allow_html=True)
        else:
            per_comp = Counter(b for pid in gaps for b in {x.brand for r in records if r.prompt.id == pid for x in r.extraction.mentions if not x.is_target})
            df_table(pd.DataFrame([{"competitor": b, "gap prompts": n} for b, n in per_comp.most_common()]))
            st.caption(f"{len(gaps)} of {m.competitor_gap.denominator} prompts with any competitor mention.")

    section("Gap prompts and evidence")
    if not m.competitor_gap_prompts:
        empty_state("No gap prompts", "The brand appears alongside every competitor that was mentioned.")
    for pid in m.competitor_gap_prompts:
        recs = [r for r in records if r.prompt.id == pid]
        comps = sorted({x.brand for r in recs for x in r.extraction.mentions if not x.is_target})
        with st.expander(f"{pmap[pid].text}  -  {', '.join(comps)}"):
            st.caption(f"{category_label(pmap[pid].category)} - prompt {short_pid(pid)} - {len(recs)} answers")
            for r in recs:
                st.markdown(f"**{r.response.provider}** &nbsp; {source_tag(r.response.source_kind)}", unsafe_allow_html=True)
                for x in r.extraction.mentions:
                    quote(x.evidence_quote, f"{x.brand} - {x.sentiment.value}" + (" - recommended" if x.recommended else ""))
