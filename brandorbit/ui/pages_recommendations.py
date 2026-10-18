from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.analysis.recommendations import generate_findings
from brandorbit.audits.catalogue_audit import audit_catalogue
from brandorbit.audits.report import build_report
from brandorbit.audits.website_audit import WebsiteAudit, inspect_live, load_snapshot
from brandorbit.core.schemas import Finding, FindingStatus, Severity
from brandorbit.monitoring.demo_loader import DEMO_DIR
from brandorbit.monitoring.runner import RunLimitError, run_monitoring
from brandorbit.providers import available_providers, first_live_provider
from brandorbit.ui.common import (
    chip, df_table, empty_state, get_repo, guard_run, hbar, kpi, page_header, quote, run_metrics, section, select_workspace, settings, short_pid,
)

SEV_RANK = {Severity.high: 0, Severity.medium: 1, Severity.low: 2}
STATUS_LABEL = {"open": "Open", "planned": "Planned", "completed": "Completed", "dismissed": "Dismissed"}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("Recommendations", "What to fix first, with the evidence behind each call.", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    tab_actions, tab_data = st.tabs(["Actions", "Product data"])
    with tab_actions:
        _actions(repo, ws, run)
    with tab_data:
        _product_data(repo, ws, run)


# ---------------------------------------------------------------- actions
def _actions(repo, ws, run) -> None:
    findings = repo.list_findings(ws.id, run.id)
    if not findings:
        empty_state("No findings for this run", "Generate findings from the stored answers.")
        if st.button("Generate findings"):
            generate_findings(repo, ws, run.id)
            st.rerun()
        return
    open_f = [f for f in findings if f.status in (FindingStatus.open, FindingStatus.planned)]
    c = st.columns([1, 1, 1, 2.2])
    with c[0]:
        kpi("Open", str(len(open_f)), help_text="Findings with status open or planned")
    with c[1]:
        kpi("High severity", str(sum(f.severity == Severity.high for f in open_f)))
    with c[2]:
        kpi("Completed", str(sum(f.status == FindingStatus.completed for f in findings)))
    with c[3]:
        show = st.multiselect("Status", list(STATUS_LABEL), default=["open", "planned"], format_func=STATUS_LABEL.get, label_visibility="collapsed")
        with st.popover("More", use_container_width=True):
            use_llm = st.checkbox("Rewrite wording with LLM", value=False, disabled=settings().demo_mode, help="Schema-validated; may only reuse existing evidence quotes. Needs a live provider.")
            if st.button("Regenerate findings for this run", use_container_width=True):
                generate_findings(repo, ws, run.id, narrator=first_live_provider() if use_llm else None)
                st.rerun()
            st.caption(f"Rules over stored extractions{' + LLM narration' if any(f.generated_by == 'rules+llm' for f in findings) else ''}. Recommendations are advisory; nothing is changed externally.")
    st.write("")

    shown = sorted([f for f in findings if f.status.value in show], key=lambda f: (SEV_RANK[f.severity], -f.confidence, f.finding_id))
    if not shown:
        empty_state("Nothing in this view", "Change the status filter to see other findings.")
    pmap = {p.id: p for p in repo.list_prompts(ws.id)}
    for f in shown:
        _finding_row(repo, ws, f, pmap)


def _finding_row(repo, ws, f: Finding, pmap) -> None:
    with st.container(border=True):
        head, status_col = st.columns([5, 1.3], vertical_alignment="center")
        with head:
            st.markdown(f"{chip(f.severity.value, f.severity.value)} &nbsp;<b>{f.title}</b>", unsafe_allow_html=True)
            st.markdown(f'<div class="bo-note">{f.category.replace("_", " ")} - confidence {f.confidence:.0%} - {f.verification_status.value} - {len(f.evidence)} evidence item{"s" if len(f.evidence) != 1 else ""}</div>', unsafe_allow_html=True)
        with status_col:
            new = st.selectbox("Status", list(STATUS_LABEL), index=list(STATUS_LABEL).index(f.status.value), format_func=STATUS_LABEL.get, key=f"st_{f.id}", label_visibility="collapsed")
            if new != f.status.value:
                repo.update_finding_status(f.id, FindingStatus(new))
                st.rerun()
        with st.expander("Why it matters, next step and evidence"):
            a, b = st.columns(2)
            a.markdown(f"**Why it matters**  \n{f.explanation}")
            b.markdown(f"**Next step**  \n{f.proposed_action}")
            st.markdown(f"**Expected outcome (hypothesis)**  \n{f.expected_outcome}")
            if f.limitations:
                st.caption(f"Limitations: {f.limitations}")
            st.markdown("**Evidence** - stored answers this finding is derived from")
            for e in f.evidence:
                p = pmap.get(e.prompt_id)
                src = f"Prompt {short_pid(e.prompt_id)}: {p.text if p else ''} - response {e.response_id}" + (f" - {e.source_url}" if e.source_url else "")
                if e.quote:
                    quote(e.quote, src)
                else:
                    st.caption(src)
            st.caption(f"{f.finding_id} - generated by {f.generated_by} - {f.created_at:%d %b %Y}")
            if f.related_prompt_ids and st.button(f"Re-run {len(f.related_prompt_ids)} related prompt{'s' if len(f.related_prompt_ids) != 1 else ''}", key=f"rr_{f.id}"):
                _rerun(repo, ws, f)


def _rerun(repo, ws, f: Finding) -> None:
    provs = available_providers()
    live = [p for p in provs.values() if p.is_live]
    chosen = live or list(provs.values())
    prompts = [p for p in repo.list_prompts(ws.id) if p.id in f.related_prompt_ids]
    try:
        with st.spinner("Running prompts..."):
            run = run_monitoring(repo, ws, chosen, prompts=prompts, label=f"Re-check {f.finding_id}", notes=f"Re-run of prompts linked to {f.finding_id}")
        st.success(f"Stored run '{run.label}' ({run.status}). Find it under Monitoring." + (" Demo providers replay fixtures, so answers mirror the fixture run." if not live else ""))
    except RunLimitError as exc:
        st.error(str(exc))


# ----------------------------------------------------------- product data
def _product_data(repo, ws, run) -> None:
    products = repo.list_products(ws.id)
    if not products:
        empty_state("No catalogue uploaded", "Add a product CSV under Settings to audit product data.")
        return
    web: WebsiteAudit | None = None
    if ws.is_demo:
        web = load_snapshot((DEMO_DIR / "website_snapshot.csv").read_bytes())
    elif "web_audit" in st.session_state:
        web = st.session_state["web_audit"]
    audit = audit_catalogue(products, ws, web.price_map() if web else None)
    sev = audit.by_severity()
    c = st.columns([1, 1, 1, 1, 2])
    with c[0]:
        kpi("Products", str(audit.products_checked))
    with c[1]:
        kpi("High", str(sev["high"]), help_text="Missing prices, cross-source price mismatches, empty descriptions")
    with c[2]:
        kpi("Medium", str(sev["medium"]))
    with c[3]:
        kpi("Low", str(sev["low"]))
    with c[4]:
        with st.popover("Website inspection", use_container_width=True):
            if ws.is_demo:
                st.caption("Demo: fictional crawl snapshot, no network requests.")
            else:
                up = st.file_uploader("Crawl snapshot CSV", type=["csv"], help="Columns: sku,page_url,listed_price,currency,has_product_schema,has_price_in_schema,has_description,title_tag")
                if up is not None and up.size <= settings().max_upload_bytes:
                    st.session_state["web_audit"] = load_snapshot(up.getvalue())
                    st.rerun()
                allow = settings().allow_website_fetch
                if st.button("Inspect up to 5 live pages", disabled=not allow, help="Enable with BRANDORBIT_ALLOW_WEBSITE_FETCH=true. Honours robots.txt."):
                    with st.spinner("Fetching..."):
                        st.session_state["web_audit"] = inspect_live(products)
                    st.rerun()
                if not allow:
                    st.caption("Live fetching is off by default (`BRANDORBIT_ALLOW_WEBSITE_FETCH`).")
        metrics = run_metrics(repo, ws, run)
        report = build_report(ws, audit, web, metrics, repo.list_findings(ws.id, run.id), ws.is_demo)
        d1, d2 = st.columns(2)
        d1.download_button("Report (.md)", report.encode("utf-8"), file_name=f"brandorbit_audit_{ws.brand.name.lower().replace(' ', '_')}.md", mime="text/markdown", use_container_width=True)
        d2.download_button("Data (.json)", repo.export_json(ws.id).encode("utf-8"), file_name=f"brandorbit_{ws.id}.json", mime="application/json", use_container_width=True)
    st.write("")

    df = audit.to_frame()
    web_issues = pd.DataFrame(web.issues()) if web else pd.DataFrame()
    if not web_issues.empty:
        web_issues["field_name"] = "page"
        web_issues["hypothesis"] = "Structured data and descriptions help answer engines read product facts."
        df = pd.concat([df, web_issues], ignore_index=True)
    if df.empty:
        st.markdown(chip("No product-data issues found", "good"), unsafe_allow_html=True)
        return
    left, right = st.columns([2, 3])
    with left:
        section("Issues by type")
        by_type = df.groupby("check").size().reset_index(name="issues").sort_values("issues", ascending=False)
        by_type["check"] = by_type["check"].str.replace("_", " ")
        hbar(by_type, "check", "issues", pct=False, height=max(140, 26 * len(by_type)))
    with right:
        section("Attribute coverage", "share of products with a value")
        cov = pd.DataFrame([{"attribute": k.replace("_", " "), "coverage": v} for k, v in audit.attribute_coverage.items()])
        hbar(cov, "attribute", "coverage", height=max(140, 26 * len(cov)))

    section("Issues", "grouped by severity - a gap is a hypothesis to test, not a proven cause")
    for sev_name in ("high", "medium", "low"):
        sub = df[df["severity"] == sev_name]
        if sub.empty:
            continue
        with st.expander(f"{sev_name.title()} - {len(sub)} issue{'s' if len(sub) != 1 else ''}", expanded=sev_name == "high"):
            view = sub[["sku", "check", "message", "hypothesis"]].copy()
            view["check"] = view["check"].str.replace("_", " ")
            df_table(view, column_config={"message": st.column_config.TextColumn("Issue", width="large"), "hypothesis": st.column_config.TextColumn("Why it may matter", width="large")})
