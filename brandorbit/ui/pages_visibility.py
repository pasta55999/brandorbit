from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label, join_records
from brandorbit.ui.common import (
    chip, coverage_line, df_table, empty_state, get_repo, grouped_bar, guard_run, hbar, page_header, run_metrics, section, select_workspace, short_pid, trend,
)


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("AI Visibility", "Where the brand shows up in AI answers, and where it does not.", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    m = run_metrics(repo, ws, run)
    brand = ws.brand.name
    brands = ws.all_brands()
    coverage_line(m)

    section("Trend across runs", "mention rate by provider")
    runs = repo.list_runs(ws.id)
    if len(runs) < 2:
        empty_state("Trend needs at least two runs")
    else:
        rows = []
        for r in runs:
            rm = run_metrics(repo, ws, r)
            rows.append({"run": r.started_at.strftime("%d %b"), "series": "All providers", "value": rm.mention_rate.value, "n": rm.mention_rate.sample})
            for prov, d in rm.by_provider.items():
                rows.append({"run": r.started_at.strftime("%d %b"), "series": prov, "value": d["mention_rate"].value, "n": d["mention_rate"].sample})
        trend(pd.DataFrame(rows), "run", "value", "series", height=220)

    left, right = st.columns(2)
    with left:
        section("By provider", "brand vs competitors")
        rows = []
        for prov, d in m.by_provider.items():
            rows.append({"provider": prov, "brand": brand, "mention rate": d["mention_rate"].value or 0, "n": d["mention_rate"].sample})
            rows += [{"provider": prov, "brand": c.name, "mention rate": d[f"mention_rate::{c.name}"].value or 0, "n": d[f"mention_rate::{c.name}"].sample} for c in ws.competitors]
        grouped_bar(pd.DataFrame(rows), "provider", "mention rate", "brand", brands)
    with right:
        section("By prompt intent", "brand mention rate")
        rows = [{"intent": category_label(k), "mention rate": v["mention_rate"].value or 0, "n": v["mention_rate"].sample} for k, v in m.by_category.items()]
        hbar(pd.DataFrame(rows), "intent", "mention rate", height=max(120, 32 * len(rows)), sort=[category_label(k) for k in m.by_category])
        rows = [{"intent": category_label(k), "website cited": v["citation_rate"].value or 0, "n": v["citation_rate"].sample} for k, v in m.by_category.items()]
        with st.expander("Website citation rate by intent"):
            hbar(pd.DataFrame(rows), "intent", "website cited", height=max(120, 32 * len(rows)), sort=[category_label(k) for k in m.by_category])

    section("Where the brand is missing", f"{len(m.absent_prompt_ids)} of {m.coverage.prompts} prompts")
    prompts = repo.list_prompts(ws.id)
    pmap = {p.id: p for p in prompts}
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    if not m.absent_prompt_ids:
        st.markdown(chip("Mentioned in every prompt", "good"), unsafe_allow_html=True)
    else:
        rows = []
        for pid in m.absent_prompt_ids:
            comps = sorted({x.brand for r in records if r.prompt.id == pid for x in r.extraction.mentions if not x.is_target})
            rows.append({"prompt": pmap[pid].text, "intent": category_label(pmap[pid].category), "competitors named": ", ".join(comps) or "-", "competitor gap": pid in m.competitor_gap_prompts, "id": short_pid(pid)})
        df_table(pd.DataFrame(rows), column_config={"competitor gap": st.column_config.CheckboxColumn(disabled=True), "prompt": st.column_config.TextColumn(width="large")})
        st.caption("Competitor gap = a competitor is named for this prompt and the brand is not. Open Competitors for the evidence.")

    with st.expander("Methodology"):
        st.markdown(
            "- **Eligible answer**: provider status `ok` with text. Failed, timed-out or malformed answers are excluded from denominators and counted as coverage gaps.\n"
            "- **Mention rate**: eligible answers mentioning the brand (any alias or its domain, word-boundary match) / eligible answers.\n"
            "- **Website cited**: eligible answers whose citations include the brand's domain / eligible answers.\n"
            "- Results reflect the specific providers, prompts and time of each run, not all consumer AI search experiences. Differences between runs do not establish causation.\n"
            "- Full definitions: `docs/METRICS.md`."
        )
