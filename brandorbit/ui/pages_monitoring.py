from __future__ import annotations

import difflib

import pandas as pd
import streamlit as st

from brandorbit.analysis.comparison import compare_runs
from brandorbit.analysis.recommendations import generate_findings
from brandorbit.core.metrics import category_label
from brandorbit.core.schemas import PromptCategory, PromptStatus
from brandorbit.monitoring.runner import RunLimitError, run_monitoring
from brandorbit.providers import available_providers
from brandorbit.ui.common import (
    chip, df_table, empty_state, get_repo, kpi, page_header, quote, raw_block, run_label, run_metrics, section, select_workspace, settings, short_pid, source_tag,
)


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    page_header("Monitoring", "Runs, before/after comparison and the raw answers behind every number.")
    t1, t2, t3 = st.tabs(["Runs", "Before & after", "Prompt explorer"])
    with t1:
        _runs(repo, ws)
    with t2:
        _compare(repo, ws)
    with t3:
        _explorer(repo, ws)


# ------------------------------------------------------------------- runs
def _runs(repo, ws) -> None:
    s = settings()
    provs = available_providers(s)
    approved = repo.list_prompts(ws.id, PromptStatus.approved)
    runs = repo.list_runs(ws.id)

    top_l, top_r = st.columns([3, 1.4], vertical_alignment="center")
    with top_l:
        section("Run history", f"{len(runs)} run{'s' if len(runs) != 1 else ''}")
    with top_r:
        with st.popover("New run", use_container_width=True):
            st.caption(f"{len(approved)} approved prompts. Limits: {s.max_prompts_per_run} prompts, {s.max_calls_per_run} calls per run.")
            options = list(provs)
            default = [p for p in options if provs[p].is_live] or options
            chosen = st.multiselect("Providers", options, default=default, format_func=lambda k: f"{k}" + (" (live)" if provs[k].is_live else " (demo fixture)"))
            label = st.text_input("Label", placeholder="e.g. After warranty page update")
            if st.button("Start run", type="primary", disabled=not chosen or not approved, use_container_width=True):
                bar = st.progress(0.0, "Starting...")
                try:
                    run = run_monitoring(repo, ws, [provs[c] for c in chosen], label=label, settings=s, progress=lambda i, n, msg: bar.progress(i / n, f"{i}/{n}"))
                    generate_findings(repo, ws, run.id)
                    st.success(f"Run finished - {run.status}.")
                    st.rerun()
                except RunLimitError as exc:
                    st.error(str(exc))
            if not approved:
                st.warning("Approve prompts under Settings first.")
    if not runs:
        empty_state("No runs yet", "Start a run to collect answers. Demo providers need no API key.")
        return
    rows = []
    for r in reversed(runs):
        m = run_metrics(repo, ws, r)
        rows.append({"date": r.started_at.strftime("%d %b %Y %H:%M"), "label": r.label, "status": r.status, "mode": "live" if r.mode.value == "live" else "demo",
                     "providers": ", ".join(r.providers), "prompts": len(r.prompt_ids), "answers": f"{m.coverage.eligible}/{m.coverage.responses_total}",
                     "mention rate": m.mention_rate.display, "baseline": r.is_baseline, "id": r.id})
    df_table(pd.DataFrame(rows), column_config={"baseline": st.column_config.CheckboxColumn(disabled=True), "answers": st.column_config.TextColumn("Answers", help="Eligible / total. Failed calls are excluded from metrics."), "id": None})
    partial = [r for r in runs if r.status == "partial"]
    if partial:
        with st.expander(f"{len(partial)} run{'s' if len(partial) != 1 else ''} with failed calls"):
            logs = [l for r in partial for l in repo.list_provider_logs(r.id) if l["status"] != "ok"]
            df_table(pd.DataFrame(logs)[["ts", "run_id", "provider", "model", "status", "latency_ms", "error"]])
            st.caption("Failed answers are stored with their error, excluded from denominators, and shown as coverage gaps.")
    pick_col, btn_col = st.columns([3, 1.4], vertical_alignment="bottom")
    pick = pick_col.selectbox("Baseline run", runs, index=next((i for i, r in enumerate(runs) if r.is_baseline), 0), format_func=run_label)
    if btn_col.button("Set as baseline", use_container_width=True):
        repo.set_baseline(ws.id, pick.id)
        st.rerun()


# ---------------------------------------------------------------- compare
def _compare(repo, ws) -> None:
    runs = repo.list_runs(ws.id)
    if len(runs) < 2:
        empty_state("Two runs are needed", "Run monitoring again, or re-run prompts from a recommendation.")
        return
    baseline = next((r for r in runs if r.is_baseline), runs[0])
    c1, c2 = st.columns(2)
    before = c1.selectbox("Before", runs, index=runs.index(baseline), format_func=run_label)
    opts = [r for r in runs if r.id != before.id]
    after = c2.selectbox("After", opts, index=len(opts) - 1, format_func=run_label)
    cmp = compare_runs(repo, ws, before.id, after.id)
    b, a = cmp.before, cmp.after
    brand = ws.brand.name

    def d(x, y):
        return None if x.value is None or y.value is None else round(y.value - x.value, 1)

    k = st.columns(4)
    with k[0]:
        kpi("Mention rate", f"{b.mention_rate.display} -> {a.mention_rate.display}", sample=f"{b.mention_rate.sample} -> {a.mention_rate.sample}", delta=d(b.mention_rate, a.mention_rate))
    with k[1]:
        kpi("Website cited", f"{b.citation_rate.display} -> {a.citation_rate.display}", sample=f"{b.citation_rate.sample} -> {a.citation_rate.sample}", delta=d(b.citation_rate, a.citation_rate))
    with k[2]:
        kpi("Share of voice", f"{b.share_of_voice[brand].display} -> {a.share_of_voice[brand].display}", delta=d(b.share_of_voice[brand], a.share_of_voice[brand]))
    with k[3]:
        kpi("Inaccurate claims", f"{b.inaccurate_claims} -> {a.inaccurate_claims}", delta=a.inaccurate_claims - b.inaccurate_claims, invert=True)
    st.write("")
    cov_note = f"{len(cmp.common_prompt_ids)} common prompts - {b.coverage.eligible} vs {a.coverage.eligible} eligible answers"
    if b.coverage.eligible != a.coverage.eligible:
        cov_note += " - coverage differs, read percentage changes with care"
    st.markdown(f'<div class="bo-note">{cov_note}. {cmp.disclaimer}</div>', unsafe_allow_html=True)

    left, right = st.columns(2)
    with left:
        section("Mentions gained", str(len(cmp.gained)))
        if cmp.gained:
            df_table(pd.DataFrame([{"prompt": p.prompt_text, "provider": p.provider} for p in cmp.gained]))
        else:
            empty_state("None")
    with right:
        section("Mentions lost", str(len(cmp.lost)))
        if cmp.lost:
            df_table(pd.DataFrame([{"prompt": p.prompt_text, "provider": p.provider} for p in cmp.lost]))
        else:
            empty_state("None")
    if cmp.coverage_mismatch:
        st.caption(f"{len(cmp.coverage_mismatch)} answer pair(s) not comparable because one side failed: " + ", ".join(f"{short_pid(p.prompt_id)}/{p.provider}" for p in cmp.coverage_mismatch))

    with st.expander("Competitor presence"):
        rows = [{"competitor": c.name, "mention rate before": b.competitor_mention_rate[c.name].display, "after": a.competitor_mention_rate[c.name].display,
                 "share of voice before": b.share_of_voice[c.name].display, "after ": a.share_of_voice[c.name].display} for c in ws.competitors]
        df_table(pd.DataFrame(rows))
        changed = [p for p in cmp.pairs if p.before_competitors != p.after_competitors and p.before_response_id and p.after_response_id]
        if changed:
            df_table(pd.DataFrame([{"prompt": p.prompt_text, "provider": p.provider, "before": ", ".join(p.before_competitors) or "-", "after": ", ".join(p.after_competitors) or "-"} for p in changed]))
    with st.expander("Cited sources"):
        c1, c2 = st.columns(2)
        c1.markdown("**New domains**  \n" + (", ".join(cmp.new_domains) or "none"))
        c2.markdown("**Dropped domains**  \n" + (", ".join(cmp.dropped_domains) or "none"))
        changed = [p for p in cmp.pairs if set(p.before_domains) != set(p.after_domains) and p.before_response_id and p.after_response_id]
        if changed:
            df_table(pd.DataFrame([{"prompt": p.prompt_text, "provider": p.provider, "before": ", ".join(p.before_domains) or "-", "after": ", ".join(p.after_domains) or "-"} for p in changed]))
    changed = [p for p in cmp.pairs if p.wording_changed]
    with st.expander(f"Answer wording - {len(changed)} changed"):
        for p in changed:
            st.markdown(f"**{short_pid(p.prompt_id)} - {p.provider}** - similarity {p.similarity} - {p.change}")
            bt = repo.get_response(p.before_response_id).text
            at = repo.get_response(p.after_response_id).text
            st.code("\n".join(difflib.unified_diff(bt.splitlines(), at.splitlines(), "before", "after", lineterm="", n=1)) or "(no line-level diff)", language="diff")
    with st.expander(f"Recommendations completed between runs - {len(cmp.implemented_findings)}"):
        if cmp.implemented_findings:
            df_table(pd.DataFrame([{"finding": f.finding_id, "title": f.title, "severity": f.severity.value} for f in cmp.implemented_findings]))
            st.caption("Listed next to the metric changes for context; this does not imply they caused the changes.")
        else:
            st.caption("No findings from the 'before' run were marked completed.")


# --------------------------------------------------------------- explorer
def _explorer(repo, ws) -> None:
    prompts = repo.list_prompts(ws.id)
    if not prompts:
        empty_state("No prompts saved", "Add or generate prompts under Settings.")
        return
    runs = {r.id: r for r in repo.list_runs(ws.id)}
    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Search", placeholder="Search prompts - e.g. warranty, air fryer", label_visibility="collapsed")
    cats = c2.multiselect("Intent", [c.value for c in PromptCategory], format_func=category_label, label_visibility="collapsed", placeholder="All intents")
    filtered = [p for p in prompts if p.status == PromptStatus.approved and (not q or q.lower() in p.text.lower()) and (not cats or p.category.value in cats)]
    if not filtered:
        empty_state("No prompts match")
        return
    rows = []
    for p in filtered:
        resps = repo.list_responses_for_prompt(p.id)
        last = max((r.created_at for r in resps), default=None)
        rows.append({"prompt": p.text, "intent": category_label(p.category), "answers": len(resps), "last run": last.strftime("%d %b %Y") if last else "never"})
    df_table(pd.DataFrame(rows), column_config={"prompt": st.column_config.TextColumn(width="large")})

    sel = st.selectbox("Inspect", filtered, format_func=lambda p: p.text)
    resps = repo.list_responses_for_prompt(sel.id)
    if not resps:
        empty_state("Not run yet")
        return
    run_ids = sorted({r.run_id for r in resps}, key=lambda rid: runs[rid].started_at if rid in runs else "")
    run_choice = st.selectbox("Run", run_ids, index=len(run_ids) - 1, format_func=lambda rid: run_label(runs[rid]) if rid in runs else rid)
    shown = [r for r in resps if r.run_id == run_choice]
    cols = st.columns(len(shown))
    for col, r in zip(cols, shown):
        with col:
            st.markdown(f"**{r.provider}** &nbsp;{source_tag(r.source_kind)} &nbsp;{chip(r.status.value, 'good' if r.status.value == 'ok' else 'bad')}", unsafe_allow_html=True)
            st.caption(f"{r.model} - {r.created_at:%d %b %Y %H:%M} - {r.latency_ms or '-'} ms" + (f" - {r.input_tokens}/{r.output_tokens} tokens" if r.input_tokens else ""))
            if r.status.value != "ok":
                st.error(f"Excluded from metrics: {r.error}")
            raw_block("Raw answer - stored verbatim", r.text)
            if r.citations:
                st.markdown("**Sources** " + " - ".join(f"[{c.domain}]({c.url})" for c in r.citations))
            ext = repo.get_extraction(r.id)
            if ext and (ext.mentions or ext.claims):
                with st.expander("Extracted analysis", expanded=False):
                    st.caption(f"Derived by the {ext.method} extractor - confidence {ext.confidence:.0%}. This is analysis, not the answer.")
                    if ext.mentions:
                        df_table(pd.DataFrame([{"brand": m.brand, "position": m.position, "rank": m.list_rank, "recommended": m.recommended, "sentiment": m.sentiment.value, "conf": m.confidence} for m in ext.mentions]))
                        for m in ext.mentions:
                            if m.is_target:
                                quote(m.evidence_quote, "evidence for the brand mention")
                    if ext.claims:
                        df_table(pd.DataFrame([{"attribute": c.attribute, "claimed": c.claimed_value, "catalogue": c.trusted_value, "status": c.verification_status.value, "product": c.product} for c in ext.claims]))
                    if ext.notes:
                        st.caption("Notes: " + "; ".join(ext.notes))
