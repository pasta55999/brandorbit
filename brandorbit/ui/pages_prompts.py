from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import category_label
from brandorbit.core.schemas import PromptCategory, SourceKind
from brandorbit.ui.common import demo_banner, get_repo, page_header, quote, select_workspace, short_pid


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    page_header("Prompt explorer", "Search saved prompts, compare raw answers across providers, and inspect citations, mentions and evidence.")
    demo_banner(ws)
    prompts = repo.list_prompts(ws.id)
    if not prompts:
        st.info("No prompts saved. Add or generate prompts in Settings.")
        return
    runs = {r.id: r for r in repo.list_runs(ws.id)}

    c1, c2, c3 = st.columns([3, 2, 2])
    q = c1.text_input("Search prompts", placeholder="e.g. warranty, air fryer, Dubai")
    cats = c2.multiselect("Category", [c.value for c in PromptCategory], format_func=category_label)
    status = c3.multiselect("Status", ["approved", "suggested", "archived"], default=["approved"])
    filtered = [p for p in prompts if (not q or q.lower() in p.text.lower()) and (not cats or p.category.value in cats) and (not status or p.status.value in status)]

    rows = []
    for p in filtered:
        resps = repo.list_responses_for_prompt(p.id)
        last = max((r.created_at for r in resps), default=None)
        rows.append({"id": short_pid(p.id), "category": category_label(p.category), "prompt": p.text, "status": p.status.value, "origin": p.origin,
                     "answers": len(resps), "last run": last.strftime("%Y-%m-%d") if last else "never"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    if not filtered:
        return

    sel = st.selectbox("Inspect prompt", filtered, format_func=lambda p: f"{short_pid(p.id)} - {p.text}")
    resps = repo.list_responses_for_prompt(sel.id)
    if not resps:
        st.info("This prompt has not been run yet.")
        return
    run_ids = sorted({r.run_id for r in resps}, key=lambda rid: runs[rid].started_at if rid in runs else "")
    run_choice = st.selectbox("Run", run_ids, index=len(run_ids) - 1, format_func=lambda rid: runs[rid].label if rid in runs else rid)
    shown = [r for r in resps if r.run_id == run_choice]
    cols = st.columns(len(shown))
    for col, r in zip(cols, shown):
        with col:
            tag = "DEMO FIXTURE" if r.source_kind == SourceKind.demo_fixture else "LIVE"
            st.markdown(f"**{r.provider}** - `{r.model}` - {tag}")
            st.caption(f"status: {r.status.value} - latency: {r.latency_ms or '-'} ms - tokens: {r.input_tokens or '-'}/{r.output_tokens or '-'} - id `{r.id}`")
            if r.status.value != "ok":
                st.error(f"Excluded from metrics: {r.error}")
            with st.container(border=True):
                st.markdown("**Raw answer (immutable)**")
                st.markdown(r.text if r.text else "_empty_")
            ext = repo.get_extraction(r.id)
            if ext:
                st.markdown("**Extracted mentions**")
                if ext.mentions:
                    st.dataframe(pd.DataFrame([{"brand": m.brand, "target": m.is_target, "pos": m.position, "rank": m.list_rank, "recommended": m.recommended,
                                                "sentiment": m.sentiment.value, "conf": m.confidence} for m in ext.mentions]), use_container_width=True, hide_index=True)
                    for m in ext.mentions:
                        if m.is_target:
                            st.caption("Evidence for target mention:")
                            quote(m.evidence_quote)
                else:
                    st.caption("No brands detected.")
                if ext.claims:
                    st.markdown("**Claims**")
                    st.dataframe(pd.DataFrame([{"attribute": c.attribute, "claimed": c.claimed_value, "trusted": c.trusted_value, "status": c.verification_status.value, "product": c.product} for c in ext.claims]), use_container_width=True, hide_index=True)
                st.markdown("**Citations**")
                if r.citations:
                    for c in r.citations:
                        st.markdown(f"- [{c.title or c.url}]({c.url}) - `{c.domain}`")
                else:
                    st.caption("None returned.")
                if ext.notes:
                    st.caption("Extractor notes: " + "; ".join(ext.notes))
                st.caption(f"extraction method: {ext.method} - confidence {ext.confidence:.0%}")
