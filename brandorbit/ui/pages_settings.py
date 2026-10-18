from __future__ import annotations

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from brandorbit.analysis.llm import suggest_prompts
from brandorbit.core.catalogue import CatalogueError, parse_catalogue_csv, products_to_frame
from brandorbit.core.metrics import category_label
from brandorbit.core.schemas import BrandProfile, Competitor, Prompt, PromptCategory, PromptStatus, Workspace
from brandorbit.monitoring.demo_loader import DEMO_WORKSPACE_ID, ensure_demo_workspace
from brandorbit.providers import available_providers, first_live_provider
from brandorbit.storage.repository import new_id
from brandorbit.ui.common import DEMO_EXPLAINER, chip, df_table, empty_state, get_repo, page_header, section, select_workspace, settings

COUNTRIES = {"United Arab Emirates": ("AE", "AED"), "Saudi Arabia": ("SA", "SAR"), "United Kingdom": ("GB", "GBP"), "United States": ("US", "USD"), "Germany": ("DE", "EUR"), "India": ("IN", "INR")}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    page_header("Settings", "Brand profile, prompt set, providers and data.")
    tabs = st.tabs(["Brand & competitors", "Product catalogue", "Prompts", "Providers & mode", "Data"])
    with tabs[0]:
        _brand_tab(repo, ws)
    with tabs[1]:
        _catalogue_tab(repo, ws)
    with tabs[2]:
        _prompts_tab(repo, ws)
    with tabs[3]:
        _providers_tab(repo, ws)
    with tabs[4]:
        _data_tab(repo, ws)


def _brand_tab(repo, ws: Workspace) -> None:
    if ws.is_demo:
        st.info("The demo workspace is read-only. Fill in the form to create your own workspace.", icon=":material/info:")
    with st.form("brand_form", border=False):
        c1, c2 = st.columns(2)
        name = c1.text_input("Brand name", ws.brand.name if not ws.is_demo else "", max_chars=80)
        website = c2.text_input("Website", ws.brand.website if not ws.is_demo else "", placeholder="https://www.example.ae")
        industry = c1.text_input("Industry", ws.brand.industry if not ws.is_demo else "", placeholder="Home & kitchen appliances")
        categories = c2.text_input("Product categories", ", ".join(ws.brand.categories) if not ws.is_demo else "", placeholder="Air fryers, Blenders", help="Comma-separated. Used for prompt suggestions.")
        country = c1.selectbox("Target country", list(COUNTRIES), index=list(COUNTRIES).index(ws.brand.country) if ws.brand.country in COUNTRIES else 0)
        currency = c2.text_input("Currency", COUNTRIES[country][1] if ws.is_demo else ws.brand.currency, max_chars=3)
        st.markdown("**Competitors** - one per line as `Name | website`")
        comp_default = "\n".join(f"{c.name} | {c.website}" for c in ws.competitors) if not ws.is_demo else ""
        comps_raw = st.text_area("Competitors", comp_default, height=110, label_visibility="collapsed", placeholder="HomeNest UAE | https://homenest.ae")
        with st.expander("Advanced"):
            language = st.selectbox("Prompt language", ["en"], help="Arabic prompt sets can be added later; language is stored per prompt.")
            aliases = st.text_input("Brand aliases", ", ".join(ws.brand.aliases) if not ws.is_demo else "", help="Other names answers might use. Avoid very short aliases - they can match unrelated words.")
        submitted = st.form_submit_button("Save workspace", type="primary")
    if submitted:
        try:
            comps = []
            for line in comps_raw.splitlines():
                if line.strip():
                    parts = [p.strip() for p in line.split("|")]
                    comps.append(Competitor(name=parts[0], website=parts[1] if len(parts) > 1 and parts[1] else ""))
            if len(comps) > 10:
                raise ValueError("Up to 10 competitors are supported.")
            brand = BrandProfile(name=name, website=website, industry=industry, categories=[c.strip() for c in categories.split(",") if c.strip()],
                                 country=country, country_code=COUNTRIES[country][0], currency=currency.upper(), language=language, aliases=[a.strip() for a in aliases.split(",") if a.strip()])
            new_ws = Workspace(id=ws.id if not ws.is_demo else new_id("ws"), name=f"{brand.name}", brand=brand, competitors=comps)
            repo.save_workspace(new_ws)
            st.session_state["workspace_id"] = new_ws.id
            st.success("Workspace saved." + (" Next: upload a catalogue and add prompts." if ws.is_demo else ""))
            st.rerun()
        except (ValidationError, ValueError) as exc:
            st.error(f"Could not save: {exc}")
    if not ws.is_demo:
        with st.expander("Delete workspace"):
            if st.button("Delete this workspace and all its data", type="secondary"):
                repo.delete_workspace(ws.id)
                st.session_state["workspace_id"] = DEMO_WORKSPACE_ID
                st.rerun()


def _catalogue_tab(repo, ws: Workspace) -> None:
    products = repo.list_products(ws.id)
    section("Product catalogue", f"{len(products)} products")
    up = st.file_uploader("Upload CSV", type=["csv"], disabled=ws.is_demo, help="Required: sku, name. Optional: category, price, currency, description, url, plus any attribute columns (capacity, power_w, warranty_years...). Max 2 MB / 2000 rows.")
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
        df_table(products_to_frame(products))
        st.caption("Product-data issues are listed under Recommendations - Product data.")
    else:
        empty_state("No catalogue yet", "Upload a CSV to enable claim verification and the product-data audit.")


def _prompts_tab(repo, ws: Workspace) -> None:
    prompts = repo.list_prompts(ws.id)
    n_appr = sum(p.status == PromptStatus.approved for p in prompts)
    n_sugg = sum(p.status == PromptStatus.suggested for p in prompts)
    section("Prompt set", f"{n_appr} approved - {n_sugg} awaiting review")
    c1, c2 = st.columns([3, 2])
    with c1:
        with st.form("add_prompt", border=False):
            a, b = st.columns([3, 1.4])
            text = a.text_input("New prompt", placeholder="What are the best ... brands in the UAE?", max_chars=500, label_visibility="collapsed")
            cat = b.selectbox("Intent", [c.value for c in PromptCategory], format_func=category_label, label_visibility="collapsed")
            if st.form_submit_button("Add approved prompt"):
                try:
                    repo.save_prompt(Prompt(id=f"{ws.id}:{new_id('p')}", workspace_id=ws.id, text=text.strip(), category=PromptCategory(cat), status=PromptStatus.approved, origin="manual"))
                    st.rerun()
                except ValidationError as exc:
                    st.error(f"Invalid prompt: {exc.errors()[0]['msg']}")
    with c2:
        live = first_live_provider()
        if st.button("Suggest prompts", use_container_width=True, help="Uses brand profile, categories, catalogue and competitors. " + ("Live LLM configured." if live else "No live LLM - deterministic templates, labelled as such.")):
            sugg, source = suggest_prompts(ws, repo.list_products(ws.id), live)
            existing = {p.text.lower() for p in prompts}
            n = 0
            for s in sugg:
                if s.text.lower() not in existing:
                    repo.save_prompt(Prompt(id=f"{ws.id}:{new_id('p')}", workspace_id=ws.id, text=s.text, category=s.category, status=PromptStatus.suggested, origin="llm_suggested" if live else "manual"))
                    n += 1
            st.success(f"{n} suggestions added for review - {source}.")
            st.rerun()
    if ws.is_demo:
        st.caption("Demo: prompts without a fixture answer are recorded as a labelled error by demo providers, never invented.")
    if not prompts:
        empty_state("No prompts yet")
        return
    df = pd.DataFrame([{"id": p.id, "prompt": p.text, "intent": category_label(p.category), "status": p.status.value, "origin": p.origin} for p in prompts])
    edited = st.data_editor(df, use_container_width=True, hide_index=True, disabled=["id", "prompt", "intent", "origin"],
                            column_config={"id": None, "prompt": st.column_config.TextColumn(width="large"), "status": st.column_config.SelectboxColumn(options=[s.value for s in PromptStatus])}, key="prompt_editor")
    b1, b2, b3, _ = st.columns([1.2, 1.4, 1.4, 3])
    if b1.button("Save changes"):
        for _, row in edited.iterrows():
            p = repo.get_prompt(row["id"])
            if p and p.status.value != row["status"]:
                p.status = PromptStatus(row["status"])
                repo.save_prompt(p)
        st.rerun()
    if b2.button("Approve suggested", disabled=not n_sugg):
        for p in prompts:
            if p.status == PromptStatus.suggested:
                p.status = PromptStatus.approved
                repo.save_prompt(p)
        st.rerun()
    if b3.button("Archive suggested", disabled=not n_sugg):
        for p in prompts:
            if p.status == PromptStatus.suggested:
                p.status = PromptStatus.archived
                repo.save_prompt(p)
        st.rerun()


def _providers_tab(repo, ws: Workspace) -> None:
    s = settings()
    section("Mode")
    if s.demo_mode:
        st.markdown(chip("Demo mode", "demo"), unsafe_allow_html=True)
        st.markdown(DEMO_EXPLAINER)
    else:
        st.markdown(chip(f"Live - {', '.join(s.live_providers)}", "live"), unsafe_allow_html=True)
        st.caption("Keys are read from the environment and never stored in the database.")
    section("Providers")
    rows = [{"provider": k, "model": p.model, "kind": "live" if p.is_live else "demo fixture", "description": p.description} for k, p in available_providers(s).items()]
    df_table(pd.DataFrame(rows))
    with st.expander("Limits and reliability"):
        st.markdown(f"- Timeout per request: {s.request_timeout_s:.0f}s - retries: {s.max_retries} (rate limits, connection errors, 5xx only)\n"
                    f"- Per run: up to {s.max_prompts_per_run} prompts and {s.max_calls_per_run} provider calls\n"
                    f"- Website fetching: {'enabled' if s.allow_website_fetch else 'disabled'} (`BRANDORBIT_ALLOW_WEBSITE_FETCH`)\n"
                    "- Change these in `.env` (see `.env.example`).")
    with st.expander("Recent provider calls"):
        logs = repo.list_provider_logs(limit=50)
        if logs:
            df_table(pd.DataFrame(logs)[["ts", "run_id", "provider", "model", "status", "latency_ms", "input_tokens", "output_tokens", "error"]])
        else:
            st.caption("No calls logged yet.")


def _data_tab(repo, ws: Workspace) -> None:
    s = settings()
    section("Data retained locally")
    st.markdown(f"SQLite database at `{s.db_path}` - workspaces, catalogue rows, prompts, runs, raw responses (immutable), extractions, findings and provider call logs. No API keys are stored. Delete the file to reset everything.")
    counts = repo.counts()
    df_table(pd.DataFrame([{"table": k, "rows": v} for k, v in counts.items()]))
    c1, c2, _ = st.columns([1.6, 1.6, 3])
    c1.download_button("Export workspace (.json)", repo.export_json(ws.id).encode("utf-8"), file_name=f"brandorbit_{ws.id}.json", mime="application/json", use_container_width=True)
    if c2.button("Reset demo workspace", use_container_width=True, help="Rebuilds the demo workspace from fixtures."):
        ensure_demo_workspace(repo, force=True)
        st.success("Demo workspace rebuilt.")
        st.rerun()
