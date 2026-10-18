from __future__ import annotations

import pandas as pd
import streamlit as st

from brandorbit.audits.catalogue_audit import audit_catalogue
from brandorbit.audits.report import build_report
from brandorbit.audits.website_audit import WebsiteAudit, inspect_live, load_snapshot
from brandorbit.core.catalogue import products_to_frame
from brandorbit.monitoring.demo_loader import DEMO_DIR
from brandorbit.ui.common import bar_chart, demo_banner, get_repo, page_header, run_metrics, select_run, select_workspace, settings


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Product-data & website audit", "Deterministic checks on the supplied catalogue and, where permitted, product pages. Gaps are hypotheses to test, not proven causes.")
    demo_banner(ws, run)
    products = repo.list_products(ws.id)
    if not products:
        st.info("No catalogue uploaded for this workspace. Upload a CSV in Settings.")
        return

    web: WebsiteAudit | None = None
    st.markdown("#### Website inspection source")
    c1, c2 = st.columns([3, 2])
    with c1:
        if ws.is_demo:
            web = load_snapshot((DEMO_DIR / "website_snapshot.csv").read_bytes())
            st.caption("Demo: using a fictional crawl snapshot (data/demo/website_snapshot.csv). No network requests are made.")
        else:
            up = st.file_uploader("Optional: upload a crawl snapshot CSV (sku,page_url,listed_price,currency,has_product_schema,has_price_in_schema,has_description,title_tag)", type=["csv"])
            if up is not None:
                if up.size > settings().max_upload_bytes:
                    st.error("File too large.")
                else:
                    web = load_snapshot(up.getvalue())
    with c2:
        allow = settings().allow_website_fetch
        if st.button("Inspect up to 5 live product pages", disabled=not allow or ws.is_demo, help="Enabled with BRANDORBIT_ALLOW_WEBSITE_FETCH=true. Respects robots.txt; reads JSON-LD, price and description only."):
            with st.spinner("Fetching pages..."):
                web = inspect_live(products)
            st.session_state["web_audit"] = web
        if "web_audit" in st.session_state and web is None:
            web = st.session_state["web_audit"]
        if not allow and not ws.is_demo:
            st.caption("Live fetching is disabled by default. Set `BRANDORBIT_ALLOW_WEBSITE_FETCH=true` to enable it.")

    audit = audit_catalogue(products, ws, web.price_map() if web else None)
    sev = audit.by_severity()
    k = st.columns(4)
    k[0].metric("Products checked", audit.products_checked)
    k[1].metric("High severity", sev["high"])
    k[2].metric("Medium severity", sev["medium"])
    k[3].metric("Low severity", sev["low"])

    t1, t2, t3, t4 = st.tabs(["Issues", "Attribute coverage", "Website checks", "Catalogue"])
    with t1:
        df = audit.to_frame()
        if df.empty:
            st.success("No issues found.")
        else:
            checks = st.multiselect("Check type", sorted(df["check"].unique()), default=sorted(df["check"].unique()))
            st.dataframe(df[df["check"].isin(checks)].sort_values(["severity", "sku"], key=lambda s: s.map({"high": 0, "medium": 1, "low": 2}) if s.name == "severity" else s),
                         use_container_width=True, hide_index=True)
            st.caption("Each issue's 'hypothesis' column explains why it may matter for AI answers. A single missing attribute does not automatically cause poor visibility.")
    with t2:
        cov = pd.DataFrame([{"attribute": k, "coverage": v} for k, v in audit.attribute_coverage.items()])
        bar_chart(cov, "attribute", "coverage", height=240)
    with t3:
        if web is None:
            st.info("No website data available. Upload a snapshot or enable live inspection.")
        else:
            st.caption(f"Source: {web.source}")
            st.dataframe(web.to_frame(), use_container_width=True, hide_index=True)
            issues = web.issues()
            if issues:
                st.dataframe(pd.DataFrame(issues), use_container_width=True, hide_index=True)
    with t4:
        st.dataframe(products_to_frame(products), use_container_width=True, hide_index=True)

    st.markdown("#### Download report")
    metrics = run_metrics(repo, ws, run) if run else None
    findings = repo.list_findings(ws.id, run.id) if run else []
    report = build_report(ws, audit, web, metrics, findings, ws.is_demo)
    st.download_button("Download Markdown report", report.encode("utf-8"), file_name=f"brandorbit_audit_{ws.brand.name.lower().replace(' ', '_')}.md", mime="text/markdown")
    st.download_button("Download workspace data (JSON)", repo.export_json(ws.id).encode("utf-8"), file_name=f"brandorbit_{ws.id}.json", mime="application/json")
