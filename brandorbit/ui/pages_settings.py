from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from brandorbit.analysis.llm import suggest_prompts
from brandorbit.analysis.recommendations import generate_findings
from brandorbit.core.catalogue import CatalogueError, parse_catalogue_csv
from brandorbit.core.metrics import category_label
from brandorbit.core.schemas import BrandProfile, Competitor, Prompt, PromptCategory, PromptStatus, Workspace
from brandorbit.monitoring.demo_loader import DEMO_WORKSPACE_ID, ensure_demo_workspace
from brandorbit.monitoring.runner import RunLimitError, run_monitoring
from brandorbit.providers import available_providers, first_live_provider
from brandorbit.storage.repository import new_id
from brandorbit.ui.common import demo_banner, get_repo, page_header, select_workspace, settings, short_pid

COUNTRIES = {"United Arab Emirates": ("AE", "AED"), "Saudi Arabia": ("SA", "SAR"), "United Kingdom": ("GB", "GBP"), "United States": ("US", "USD"), "Germany": ("DE", "EUR"), "India": ("IN", "INR")}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    page_header("Settings", "Configure the brand, competitors, catalogue and prompt set; run monitoring; manage providers.")
    demo_banner(ws)
    tabs = st.tabs(["Brand & competitors", "Product catalogue", "Prompts", "Run monitoring", "Providers & data"])
    with tabs[0]:
        _brand_tab(repo, ws)
    with tabs[1]:
        _catalogue_tab(repo, ws)
    with tabs[2]:
        _prompts_tab(repo, ws)
    with tabs[3]:
        _run_tab(repo, ws)
    with tabs[4]:
        _providers_tab(repo, ws)


def _brand_tab(repo, ws: Workspace) -> None:
    st.markdown("#### Edit current workspace" if not ws.is_demo else "#### Demo workspace (read-only) - create your own below")
    with st.form("brand_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Brand name *", ws.brand.name if not ws.is_demo else "", max_chars=80)
        website = c2.text_input("Website *", ws.brand.website if not ws.is_demo else "", placeholder="https://www.example.ae")
        industry = c1.text_input("Industry *", ws.brand.industry if not ws.is_demo else "", placeholder="Home & kitchen appliances")
        categories = c2.text_input("Product categories (comma-separated)", ", ".join(ws.brand.categories) if not ws.is_demo else "")
        country = c1.selectbox("Target country", list(COUNTRIES), index=list(COUNTRIES).index(ws.brand.country) if ws.brand.country in COUNTRIES else 0)
        currency = c2.text_input("Currency", COUNTRIES[country][1] if ws.is_demo else ws.brand.currency, max_chars=3)
        language = c1.selectbox("Prompt language", ["en"], help="Arabic prompt sets can be added later; the data model stores a language per prompt.")
        aliases = c2.text_input("Brand aliases (comma-separated)", ", ".join(ws.brand.aliases) if not ws.is_demo else "")
        st.markdown("**Competitors** (one per line: `Name | website`)")
        comp_default = "\n".join(f"{c.name} | {c.website}" for c in ws.competitors) if not ws.is_demo else ""
        comps_raw = st.text_area("Competitors", comp_default, height=120, label_visibility="collapsed", placeholder="HomeNest UAE | https://homenest.ae")
        submitted = st.form_submit_button("Save workspace", type="primary")
    if submitted:
        try:
            comps = []
            for line in comps_raw.splitlines():
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split("|")]
                comps.append(Competitor(name=parts[0], website=parts[1] if len(parts) > 1 and parts[1] else ""))
            if len(comps) > 10:
                raise ValueError("Up to 10 competitors are supported.")
            brand = BrandProfile(name=name, website=website, industry=industry, categories=[c.strip() for c in categories.split(",") if c.strip()],
                                 country=country, country_code=COUNTRIES[country][0], currency=currency.upper(), language=language,
                                 aliases=[a.strip() for a in aliases.split(",") if a.strip()])
            new_ws = Workspace(id=ws.id if not ws.is_demo else new_id("ws"), name=f"{brand.name} workspace", brand=brand, competitors=comps)
            repo.save_workspace(new_ws)
            st.session_state["workspace_id"] = new_ws.id
            st.success(f"Saved workspace '{new_ws.name}'. " + ("Now upload a catalogue and add prompts." if ws.is_demo else ""))
            st.rerun()
        except (ValidationError, ValueError) as exc:
            st.error(f"Could not save: {exc}")
    if not ws.is_demo:
        with st.expander("Danger zone"):
            if st.button("Delete this workspace and all its data"):
                repo.delete_workspace(ws.id)
                st.session_state["workspace_id"] = DEMO_WORKSPACE_ID
                st.rerun()


def _catalogue_tab(repo, ws: Workspace) -> None:
    products = repo.list_products(ws.id)
    st.markdown(f"#### Product catalogue - {len(products)} products")
    st.caption("CSV with required columns `sku,name`; optional `category,price,currency,description,url` and any extra attribute columns (e.g. `capacity,power_w,warranty_years`). Max 2 MB / 2000 rows.")
    up = st.file_uploader("Upload CSV", type=["csv"], disabled=ws.is_demo)
    if up is not None:
        if up.size > settings().max_upload_bytes:
            st.error("File exceeds 2 MB.")
        else:
            try:
                prods = parse_catalogue_csv(up.getvalue(), ws.brand.currency, settings().max_upload_bytes)
                repo.replace_products(ws.id, prods)
                st.success(f"Imported {len(prods)} products.")
                products = prods
            except CatalogueError as exc:
                st.error(str(exc))
    if products:
        from brandorbit.core.catalogue import products_to_frame
        st.dataframe(products_to_frame(products), use_container_width=True, hide_index=True)


def _prompts_tab(repo, ws: Workspace) -> None:
    prompts = repo.list_prompts(ws.id)
    st.markdown(f"#### Prompt set - {sum(p.status == PromptStatus.approved for p in prompts)} approved, {sum(p.status == PromptStatus.suggested for p in prompts)} awaiting review")
    c1, c2 = st.columns([3, 2])
    with c1:
        with st.form("add_prompt"):
            text = st.text_input("New prompt", placeholder="What are the best ... brands in the UAE?", max_chars=500)
            cat = st.selectbox("Category", [c.value for c in PromptCategory], format_func=category_label)
            if st.form_submit_button("Add prompt (approved)"):
                try:
                    repo.save_prompt(Prompt(id=f"{ws.id}:{new_id('p')}", workspace_id=ws.id, text=text.strip(), category=PromptCategory(cat), status=PromptStatus.approved, origin="manual"))
                    st.rerun()
                except ValidationError as exc:
                    st.error(f"Invalid prompt: {exc.errors()[0]['msg']}")
    with c2:
        live = first_live_provider()
        st.markdown("**Generate suggestions**")
        st.caption("Uses the brand profile, categories, catalogue and competitors. " + ("A live LLM is configured." if live else "No live LLM configured - deterministic templates will be used and labelled as such."))
        if st.button("Generate suggested prompts"):
            sugg, source = suggest_prompts(ws, repo.list_products(ws.id), live)
            existing = {p.text.lower() for p in prompts}
            n = 0
            for s in sugg:
                if s.text.lower() not in existing:
                    repo.save_prompt(Prompt(id=f"{ws.id}:{new_id('p')}", workspace_id=ws.id, text=s.text, category=s.category, status=PromptStatus.suggested, origin="llm_suggested" if live else "manual"))
                    n += 1
            st.success(f"{n} suggestions added for review ({source}).")
            st.rerun()
    if ws.is_demo:
        st.caption("Demo note: new prompts have no fixture answers, so demo providers will record a clearly-labelled error for them rather than inventing an answer.")
    if not prompts:
        st.info("No prompts yet.")
        return
    st.markdown("**Review prompts** - edit status inline, then click Save.")
    df = pd.DataFrame([{"id": p.id, "short": short_pid(p.id), "category": category_label(p.category), "prompt": p.text, "status": p.status.value, "origin": p.origin} for p in prompts])
    edited = st.data_editor(df, use_container_width=True, hide_index=True, disabled=["id", "short", "category", "prompt", "origin"],
                            column_config={"id": None, "status": st.column_config.SelectboxColumn(options=[s.value for s in PromptStatus])}, key="prompt_editor")
    b1, b2, b3 = st.columns(3)
    if b1.button("Save status changes"):
        for _, row in edited.iterrows():
            p = repo.get_prompt(row["id"])
            if p and p.status.value != row["status"]:
                p.status = PromptStatus(row["status"])
                repo.save_prompt(p)
        st.rerun()
    if b2.button("Approve all suggested"):
        for p in prompts:
            if p.status == PromptStatus.suggested:
                p.status = PromptStatus.approved
                repo.save_prompt(p)
        st.rerun()
    if b3.button("Archive all suggested"):
        for p in prompts:
            if p.status == PromptStatus.suggested:
                p.status = PromptStatus.archived
                repo.save_prompt(p)
        st.rerun()


def _run_tab(repo, ws: Workspace) -> None:
    s = settings()
    provs = available_providers(s)
    approved = repo.list_prompts(ws.id, PromptStatus.approved)
    st.markdown("#### Run AI search monitoring")
    st.caption(f"{len(approved)} approved prompts. Limits: {s.max_prompts_per_run} prompts and {s.max_calls_per_run} provider calls per run.")
    options = list(provs)
    default = [p for p in options if provs[p].is_live] or options
    chosen = st.multiselect("Providers", options, default=default, format_func=lambda k: f"{k} - {provs[k].description}")
    label = st.text_input("Run label", "")
    if any(not provs[c].is_live for c in chosen):
        st.info("Demo providers replay fixture answers for the demo prompt set only. Results are labelled DEMO FIXTURE throughout the app.")
    if st.button("Start run", type="primary", disabled=not chosen or not approved):
        bar = st.progress(0.0, "Starting...")
        try:
            run = run_monitoring(repo, ws, [provs[c] for c in chosen], label=label, settings=s,
                                 progress=lambda i, n, msg: bar.progress(i / n, f"{i}/{n} - {msg}"))
            generate_findings(repo, ws, run.id)
            bar.progress(1.0, "Done")
            st.success(f"Run '{run.label}' finished with status **{run.status}**. Findings generated. Select it in the sidebar.")
        except RunLimitError as exc:
            st.error(str(exc))
    runs = repo.list_runs(ws.id)
    if runs:
        st.markdown("**Stored runs**")
        st.dataframe(pd.DataFrame([{"id": r.id, "label": r.label, "started": r.started_at.strftime("%Y-%m-%d %H:%M"), "mode": r.mode.value, "providers": ", ".join(r.providers),
                                    "prompts": len(r.prompt_ids), "status": r.status, "baseline": r.is_baseline} for r in runs]), use_container_width=True, hide_index=True)
        pick = st.selectbox("Set baseline run", runs, format_func=lambda r: r.label)
        if st.button("Save as baseline"):
            repo.set_baseline(ws.id, pick.id)
            st.rerun()


def _providers_tab(repo, ws: Workspace) -> None:
    s = settings()
    st.markdown("#### Provider status")
    if s.demo_mode:
        st.warning("**Demo mode** - no API keys detected. The app is fully usable with fixture data. To enable live monitoring, copy `.env.example` to `.env` and set `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`, then restart.")
    else:
        st.success(f"Live providers configured: {', '.join(s.live_providers)}. Keys are read from the environment and never stored in the database.")
    rows = [{"provider": k, "model": p.model, "kind": "live" if p.is_live else "demo fixture", "description": p.description} for k, p in available_providers(s).items()]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("#### Recent provider calls")
    logs = repo.list_provider_logs(limit=50)
    if logs:
        st.dataframe(pd.DataFrame(logs)[["ts", "run_id", "provider", "model", "status", "latency_ms", "input_tokens", "output_tokens", "error"]], use_container_width=True, hide_index=True)
    st.markdown("#### Data retained locally")
    st.caption(f"SQLite database at `{s.db_path}`: workspaces, catalogue rows, prompts, runs, raw responses (immutable), extractions, findings and provider call logs. No API keys are stored. Delete the file to reset.")
    counts = repo.counts()
    st.json(counts, expanded=False)
    if st.button("Reset demo workspace to fixtures"):
        ensure_demo_workspace(repo, force=True)
        st.success("Demo workspace rebuilt.")
        st.rerun()
