from __future__ import annotations

import difflib

import pandas as pd
import streamlit as st

from brandorbit.analysis.comparison import compare_runs
from brandorbit.ui.common import demo_banner, get_repo, metric_card, page_header, select_workspace, short_pid


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    page_header("Before & after", "Compare a saved baseline with a later run over the same prompts.")
    demo_banner(ws)
    runs = repo.list_runs(ws.id)
    if len(runs) < 2:
        st.info("At least two runs are needed. Run monitoring again from Settings, or re-run prompts from a recommendation.")
        return
    baseline = next((r for r in runs if r.is_baseline), runs[0])
    c1, c2, c3 = st.columns([3, 3, 2])
    before = c1.selectbox("Before (baseline)", runs, index=runs.index(baseline), format_func=lambda r: r.label + ("  (baseline)" if r.is_baseline else ""))
    after_opts = [r for r in runs if r.id != before.id]
    after = c2.selectbox("After", after_opts, index=len(after_opts) - 1, format_func=lambda r: r.label)
    with c3:
        st.write("")
        if st.button("Save 'before' run as baseline", use_container_width=True):
            repo.set_baseline(ws.id, before.id)
            st.rerun()
    cmp = compare_runs(repo, ws, before.id, after.id)
    st.warning(cmp.disclaimer)
    b, a = cmp.before, cmp.after
    st.caption(f"Compared over {len(cmp.common_prompt_ids)} prompts present in both runs. Before: {b.coverage.eligible} eligible answers ({b.coverage.failed} failed). After: {a.coverage.eligible} eligible ({a.coverage.failed} failed)."
               + (" Coverage differs - interpret percentage changes with care." if b.coverage.eligible != a.coverage.eligible else ""))

    def d(x, y):
        return None if x.value is None or y.value is None else round(y.value - x.value, 1)

    cols = st.columns(5)
    with cols[0]:
        metric_card("Mention rate", f"{b.mention_rate.display} -> {a.mention_rate.display}", f"n {b.mention_rate.sample} -> {a.mention_rate.sample}", d(b.mention_rate, a.mention_rate))
    with cols[1]:
        metric_card("Citation rate", f"{b.citation_rate.display} -> {a.citation_rate.display}", f"n {b.citation_rate.sample} -> {a.citation_rate.sample}", d(b.citation_rate, a.citation_rate))
    with cols[2]:
        bs, as_ = b.share_of_voice[ws.brand.name], a.share_of_voice[ws.brand.name]
        metric_card("Share of voice", f"{bs.display} -> {as_.display}", f"n {bs.sample} -> {as_.sample}", d(bs, as_))
    with cols[3]:
        metric_card("Inaccurate claims", f"{b.inaccurate_claims} -> {a.inaccurate_claims}", f"accuracy {b.accuracy.display} -> {a.accuracy.display}")
    with cols[4]:
        metric_card("Competitor gaps", f"{len(b.competitor_gap_prompts)} -> {len(a.competitor_gap_prompts)}", "prompts with competitor but no brand")

    st.write("")
    t1, t2, t3, t4, t5 = st.tabs(["Mention changes", "Competitor presence", "Cited sources", "Answer wording", "Implemented recommendations"])
    with t1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Newly appearing brand mentions ({len(cmp.gained)})**")
            st.dataframe(pd.DataFrame([{"prompt": short_pid(p.prompt_id), "provider": p.provider, "text": p.prompt_text} for p in cmp.gained]), use_container_width=True, hide_index=True) if cmp.gained else st.caption("None")
        with c2:
            st.markdown(f"**Disappearing brand mentions ({len(cmp.lost)})**")
            st.dataframe(pd.DataFrame([{"prompt": short_pid(p.prompt_id), "provider": p.provider, "text": p.prompt_text} for p in cmp.lost]), use_container_width=True, hide_index=True) if cmp.lost else st.caption("None")
        if cmp.coverage_mismatch:
            st.markdown(f"**Coverage differs ({len(cmp.coverage_mismatch)})** - an answer failed or is missing in one of the runs:")
            st.dataframe(pd.DataFrame([{"prompt": short_pid(p.prompt_id), "provider": p.provider, "before": p.before_mentioned, "after": p.after_mentioned} for p in cmp.coverage_mismatch]), use_container_width=True, hide_index=True)
    with t2:
        rows = []
        for c in ws.competitors:
            rows.append({"competitor": c.name, "mention rate before": b.competitor_mention_rate[c.name].display, "after": a.competitor_mention_rate[c.name].display,
                         "SoV before": b.share_of_voice[c.name].display, "SoV after": a.share_of_voice[c.name].display})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        changed = [p for p in cmp.pairs if p.before_competitors != p.after_competitors and p.before_response_id and p.after_response_id]
        if changed:
            st.markdown("**Answers where the competitor set changed**")
            st.dataframe(pd.DataFrame([{"prompt": short_pid(p.prompt_id), "provider": p.provider, "before": ", ".join(p.before_competitors) or "-", "after": ", ".join(p.after_competitors) or "-"} for p in changed]), use_container_width=True, hide_index=True)
    with t3:
        c1, c2 = st.columns(2)
        c1.markdown("**New domains**"); c1.write(cmp.new_domains or "None")
        c2.markdown("**Dropped domains**"); c2.write(cmp.dropped_domains or "None")
        changed = [p for p in cmp.pairs if set(p.before_domains) != set(p.after_domains) and p.before_response_id and p.after_response_id]
        if changed:
            st.dataframe(pd.DataFrame([{"prompt": short_pid(p.prompt_id), "provider": p.provider, "before": ", ".join(p.before_domains) or "-", "after": ", ".join(p.after_domains) or "-"} for p in changed]), use_container_width=True, hide_index=True)
    with t4:
        changed = [p for p in cmp.pairs if p.wording_changed]
        st.caption(f"{len(changed)} answer pairs changed wording (similarity < 0.98). Unchanged pairs are hidden.")
        for p in changed:
            with st.expander(f"{short_pid(p.prompt_id)} - {p.provider} - similarity {p.similarity} - {p.change}"):
                bt = repo.get_response(p.before_response_id).text
                at = repo.get_response(p.after_response_id).text
                diff = difflib.unified_diff(bt.splitlines(), at.splitlines(), "before", "after", lineterm="", n=1)
                st.code("\n".join(diff) or "(no line-level diff)", language="diff")
    with t5:
        if cmp.implemented_findings:
            st.dataframe(pd.DataFrame([{"finding": f.finding_id, "title": f.title, "severity": f.severity.value, "status": f.status.value} for f in cmp.implemented_findings]), use_container_width=True, hide_index=True)
            st.caption("Findings from the 'before' run marked as completed. Listing them next to the metric changes does not imply they caused the changes.")
        else:
            st.caption("No recommendations from the baseline run were marked completed.")
