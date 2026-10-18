from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd
import streamlit as st

from brandorbit.analysis.extraction import extract_citations
from brandorbit.core.metrics import join_records
from brandorbit.ui.common import bar_chart, coverage_caption, demo_banner, get_repo, page_header, run_metrics, select_run, select_workspace, short_pid


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Citation intelligence", "Which sources AI answers cite, and which ones appear alongside brand or competitor mentions.")
    demo_banner(ws, run)
    if run is None:
        st.info("No runs yet.")
        return
    m = run_metrics(repo, ws, run)
    coverage_caption(m)
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    comps = {c.name for c in ws.competitors}
    comp_domains = {c.domain: c.name for c in ws.competitors}

    domain_rows = defaultdict(lambda: {"answers": 0, "with brand mention": 0, "with competitor mention": 0, "urls": set(), "prompts": set()})
    url_rows = Counter()
    url_title = {}
    no_cite = 0
    for r in records:
        cits = extract_citations(r.response)
        if not cits:
            no_cite += 1
        for c in {c.domain: c for c in cits}.values():
            d = domain_rows[c.domain]
            d["answers"] += 1
            d["with brand mention"] += int(r.extraction.target_mentioned)
            d["with competitor mention"] += int(bool(r.brands_mentioned & comps))
            d["prompts"].add(short_pid(r.prompt.id))
        for c in cits:
            url_rows[c.url] += 1
            url_title[c.url] = c.title
            domain_rows[c.domain]["urls"].add(c.url)

    def owner(domain: str) -> str:
        if domain == ws.brand.domain:
            return "brand site"
        if domain in comp_domains:
            return f"competitor ({comp_domains[domain]})"
        return "third party"

    c1, c2, c3 = st.columns(3)
    c1.metric("Answers with any citation", f"{len(records) - no_cite}/{len(records)}")
    c2.metric("Distinct domains cited", len(domain_rows))
    c3.metric("Brand website citation rate", m.citation_rate.display, help=m.citation_rate.definition + f" (n = {m.citation_rate.sample})")
    if no_cite:
        st.caption(f"{no_cite} eligible answers returned no citations (typically providers without web search). They count in denominators.")

    st.markdown("#### Cited domains")
    df = pd.DataFrame([{"domain": d, "type": owner(d), **{k: v for k, v in row.items() if k not in ("urls", "prompts")}, "distinct URLs": len(row["urls"]), "prompts": ", ".join(sorted(row["prompts"]))}
                       for d, row in domain_rows.items()]).sort_values("answers", ascending=False) if domain_rows else pd.DataFrame()
    if df.empty:
        st.info("No citations in this run.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Sources associated with brand mentions")
        sub = df[df["with brand mention"] > 0][["domain", "with brand mention"]].rename(columns={"with brand mention": "answers with brand"})
        bar_chart(sub, "domain", "answers with brand", pct=False, height=240)
    with c2:
        st.markdown("#### Sources when competitors are recommended")
        sub = df[df["with competitor mention"] > 0][["domain", "with competitor mention"]].rename(columns={"with competitor mention": "answers with competitor"})
        bar_chart(sub, "domain", "answers with competitor", pct=False, height=240)

    st.markdown("#### Pages worth investigating")
    st.caption("Third-party URLs cited most often in answers that mention the brand or a competitor. Review what they say; outdated pages are a common source of inaccurate claims.")
    rows = [{"url": u, "title": url_title.get(u, ""), "cited in answers": n, "type": owner(u.split("/")[2].replace("www.", ""))} for u, n in url_rows.most_common(25)]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, column_config={"url": st.column_config.LinkColumn()})
    if ws.is_demo:
        st.caption("Demo note: every domain and URL above is fictional and does not resolve.")
