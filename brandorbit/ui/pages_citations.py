from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd
import streamlit as st

from brandorbit.analysis.extraction import extract_citations
from brandorbit.core.metrics import join_records
from brandorbit.core.schemas import domain_of
from brandorbit.ui.common import coverage_line, df_table, empty_state, get_repo, guard_run, hbar, kpi, metric_kpi, page_header, run_metrics, section, select_workspace, short_pid


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("Sources & Citations", "Which pages AI answers lean on - yours, competitors', or third parties'.", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    m = run_metrics(repo, ws, run)
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    comps = {c.name for c in ws.competitors}
    comp_domains = {c.domain: c.name for c in ws.competitors}

    def owner(domain: str) -> str:
        if domain == ws.brand.domain:
            return "Your site"
        return f"Competitor - {comp_domains[domain]}" if domain in comp_domains else "Third party"

    dom = defaultdict(lambda: {"answers": 0, "with brand": 0, "with competitor": 0, "urls": Counter(), "titles": {}})
    no_cite = 0
    for r in records:
        cits = extract_citations(r.response)
        if not cits:
            no_cite += 1
        for d in {c.domain for c in cits if c.domain}:
            dom[d]["answers"] += 1
            dom[d]["with brand"] += int(r.extraction.target_mentioned)
            dom[d]["with competitor"] += int(bool(r.brands_mentioned & comps))
        for c in cits:
            dom[c.domain]["urls"][c.url] += 1
            dom[c.domain]["titles"][c.url] = c.title

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi("Answers with citations", f"{len(records) - no_cite}/{len(records)}", help_text="Eligible answers that returned at least one source. Providers without web search return none.")
    with c2:
        metric_kpi("Your site cited", m.citation_rate, help_text="Eligible answers citing the brand's domain.")
    with c3:
        kpi("Distinct domains", str(len(dom)), help_text="Unique domains across provider citations and inline URLs.")
    st.write("")
    coverage_line(m)
    if not dom:
        empty_state("No citations in this run", "The selected providers did not return sources.")
        return

    df = pd.DataFrame([{"domain": d, "type": owner(d), "answers": v["answers"], "with brand": v["with brand"], "with competitor": v["with competitor"], "urls": len(v["urls"])} for d, v in dom.items()]).sort_values("answers", ascending=False)
    left, right = st.columns([3, 2])
    with left:
        section("Cited domains")
        df_table(df, column_config={"answers": st.column_config.NumberColumn("Answers"), "with brand": st.column_config.NumberColumn("w/ brand mention"), "with competitor": st.column_config.NumberColumn("w/ competitor"), "urls": st.column_config.NumberColumn("URLs")})
    with right:
        section("Sources supporting competitors")
        sub = df[(df["with competitor"] > 0) & (df["type"] != "Your site")].head(8)
        hbar(sub[["domain", "with competitor"]].rename(columns={"with competitor": "answers"}), "domain", "answers", pct=False, height=max(120, 28 * len(sub)))

    section("Brand mentioned but your site not cited", "prompts where a third-party page carries the narrative")
    rows = []
    for r in records:
        if r.extraction.target_mentioned and not r.extraction.target_cited and r.extraction.cited_domains:
            rows.append({"prompt": r.prompt.text, "provider": r.response.provider, "sources cited": ", ".join(r.extraction.cited_domains), "id": short_pid(r.prompt.id)})
    if rows:
        df_table(pd.DataFrame(rows), column_config={"prompt": st.column_config.TextColumn(width="large")})
    else:
        empty_state("No such answers", "Whenever the brand was mentioned with sources, your site was among them.")

    with st.expander("All cited URLs"):
        urls = [{"url": u, "title": v["titles"].get(u, ""), "domain": d, "type": owner(d), "cited": n} for d, v in dom.items() for u, n in v["urls"].items()]
        df_table(pd.DataFrame(urls).sort_values("cited", ascending=False), column_config={"url": st.column_config.LinkColumn("URL")})
        if ws.is_demo:
            st.caption("Demo workspace: all domains and URLs are fictional and do not resolve.")
