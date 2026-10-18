"""Shared UI helpers: repository access, styling, selectors and small components."""

from __future__ import annotations

from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from brandorbit.core.config import Settings, get_settings
from brandorbit.core.metrics import MetricValue, RunMetrics, compute_run_metrics
from brandorbit.core.schemas import MonitoringRun, SourceKind, Workspace
from brandorbit.monitoring.demo_loader import DEMO_WORKSPACE_ID, ensure_demo_workspace
from brandorbit.storage.repository import Repository

NAVY = "#0F1D3A"
ACCENT = "#2F80ED"
ACCENT_2 = "#F2994A"
MUTED = "#6B7280"
PALETTE = ["#2F80ED", "#0F1D3A", "#F2994A", "#27AE60", "#9B51E0", "#EB5757", "#56CCF2"]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px; }}
section[data-testid="stSidebar"] {{ background: {NAVY}; }}
section[data-testid="stSidebar"] * {{ color: #E5E9F2 !important; }}
section[data-testid="stSidebar"] a[aria-current="page"] {{ background: rgba(47,128,237,0.25) !important; border-radius: 8px; }}
section[data-testid="stSidebar"] a:hover {{ background: rgba(255,255,255,0.06) !important; border-radius: 8px; }}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{ background: #1B2B4F; border-color: #2B3D63; }}
.bo-brand {{ display:flex; align-items:center; gap:10px; padding: 4px 0 14px 0; }}
.bo-brand h1 {{ font-size: 1.25rem; margin: 0; color: #fff !important; letter-spacing: .2px; }}
.bo-brand small {{ color: #A9B4CC !important; font-size: .72rem; display:block; }}
.bo-badge {{ display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: .72rem; font-weight: 600; letter-spacing: .3px; }}
.bo-badge.demo {{ background: #FFF4E5; color: #9A5B00; border: 1px solid #F5C77E; }}
.bo-badge.live {{ background: #E6F6EC; color: #1E7A3B; border: 1px solid #9ED8B2; }}
.bo-badge.sev-high {{ background:#FDE8E8; color:#B42318; }}
.bo-badge.sev-medium {{ background:#FFF4E5; color:#9A5B00; }}
.bo-badge.sev-low {{ background:#EEF2FF; color:#3730A3; }}
.bo-card {{ background: #fff; border: 1px solid #E5E7EB; border-radius: 12px; padding: 16px 18px; height: 100%; }}
.bo-card .label {{ color: {MUTED}; font-size: .78rem; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }}
.bo-card .value {{ color: {NAVY}; font-size: 1.9rem; font-weight: 700; line-height: 1.15; margin-top: 4px; }}
.bo-card .sub {{ color: {MUTED}; font-size: .78rem; margin-top: 4px; }}
.bo-card .delta-up {{ color: #1E7A3B; font-weight: 600; }}
.bo-card .delta-down {{ color: #B42318; font-weight: 600; }}
.bo-note {{ background: #F8FAFC; border-left: 3px solid {ACCENT}; padding: 10px 14px; border-radius: 6px; color: #334155; font-size: .86rem; }}
.bo-quote {{ border-left: 3px solid #CBD5E1; padding: 6px 12px; color: #334155; font-style: italic; background:#FAFAFA; border-radius: 4px; margin: 4px 0 8px 0; }}
.bo-demo-banner {{ background: #FFF8EC; border: 1px solid #F5C77E; border-radius: 10px; padding: 10px 14px; font-size: .86rem; color: #7A4B00; margin-bottom: 14px; }}
h1, h2, h3 {{ color: {NAVY}; }}
h1 {{ font-weight: 700; letter-spacing: -.3px; }}
[data-testid="stMetricValue"] {{ color: {NAVY}; }}
</style>
"""

ORBIT_SVG = """
<svg width="34" height="34" viewBox="0 0 34 34" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="BrandOrbit logo">
<circle cx="17" cy="17" r="15" stroke="#2F80ED" stroke-width="1.5" stroke-dasharray="3 3" opacity=".9"/>
<ellipse cx="17" cy="17" rx="15" ry="6.5" stroke="#F2994A" stroke-width="1.4" transform="rotate(-25 17 17)"/>
<circle cx="17" cy="17" r="4.2" fill="#FFFFFF"/>
<circle cx="29.5" cy="11" r="2.1" fill="#F2994A"/>
</svg>
"""


@st.cache_resource(show_spinner=False)
def get_repo() -> Repository:
    settings = get_settings()
    repo = Repository(settings.db_path)
    ensure_demo_workspace(repo)
    return repo


def settings() -> Settings:
    return get_settings()


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def sidebar_header() -> None:
    st.sidebar.markdown(f'<div class="bo-brand">{ORBIT_SVG}<div><h1>BrandOrbit</h1><small>See how AI sees your brand</small></div></div>', unsafe_allow_html=True)


def mode_badge() -> str:
    s = settings()
    if s.demo_mode:
        return '<span class="bo-badge demo">DEMO MODE - fixture data</span>'
    return f'<span class="bo-badge live">LIVE: {", ".join(s.live_providers)}</span>'


def select_workspace(repo: Repository) -> Workspace:
    wss = repo.list_workspaces()
    ids = [w.id for w in wss]
    current = st.session_state.get("workspace_id", DEMO_WORKSPACE_ID)
    if current not in ids:
        current = ids[0]
    choice = st.sidebar.selectbox("Workspace", ids, index=ids.index(current), format_func=lambda i: next(w.name for w in wss if w.id == i), key="workspace_select")
    st.session_state["workspace_id"] = choice
    return repo.get_workspace(choice)


def select_run(repo: Repository, ws: Workspace, label: str = "Monitoring run", key: str = "run_select", default_latest: bool = True) -> Optional[MonitoringRun]:
    runs = repo.list_runs(ws.id)
    if not runs:
        return None
    runs = list(reversed(runs))
    idx = 0 if default_latest else len(runs) - 1
    fmt = lambda r: f"{r.label}{'  (baseline)' if r.is_baseline else ''}{'  [partial]' if r.status == 'partial' else ''}"  # noqa: E731
    return st.sidebar.selectbox(label, runs, index=idx, format_func=fmt, key=key)


def run_metrics(repo: Repository, ws: Workspace, run: MonitoringRun) -> RunMetrics:
    return compute_run_metrics(ws, repo.list_prompts(ws.id), repo.list_responses(run.id), repo.list_extractions(run.id))


def demo_banner(ws: Workspace, run: Optional[MonitoringRun] = None) -> None:
    if ws.is_demo or (run and run.mode == SourceKind.demo_fixture):
        st.markdown(
            '<div class="bo-demo-banner"><b>Demo data.</b> This workspace uses hand-written, clearly labelled fixture answers for a fictional brand. '
            "They simulate the <i>style</i> of AI shopping answers and are not outputs of any real AI system. Configure an API key in <code>.env</code> to monitor live providers.</div>",
            unsafe_allow_html=True,
        )


def page_header(title: str, subtitle: str = "") -> None:
    c1, c2 = st.columns([5, 2])
    with c1:
        st.markdown(f"## {title}")
        if subtitle:
            st.caption(subtitle)
    with c2:
        st.markdown(f'<div style="text-align:right;padding-top:14px">{mode_badge()}</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, sub: str = "", delta: Optional[float] = None, help_text: str = "") -> None:
    delta_html = ""
    if delta is not None:
        cls = "delta-up" if delta > 0 else ("delta-down" if delta < 0 else "")
        delta_html = f' <span class="{cls}">{delta:+.1f} pts</span>'
    title_attr = f' title="{help_text}"' if help_text else ""
    st.markdown(f'<div class="bo-card"{title_attr}><div class="label">{label}</div><div class="value">{value}{delta_html}</div><div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def metric_sub(m: MetricValue) -> str:
    return f"n = {m.sample} - {m.definition}"


def severity_badge(sev: str) -> str:
    return f'<span class="bo-badge sev-{sev}">{sev.upper()}</span>'


def quote(text: str) -> None:
    if text:
        st.markdown(f'<div class="bo-quote">"{text}"</div>', unsafe_allow_html=True)


def bar_chart(df: pd.DataFrame, x: str, y: str, color: Optional[str] = None, title: str = "", horizontal: bool = True, pct: bool = True, height: int = 260):
    if df.empty:
        st.info("No data for this chart yet.")
        return
    enc_val = alt.Y if not horizontal else alt.X
    enc_cat = alt.X if not horizontal else alt.Y
    axis = alt.Axis(format=".0f", title=("%" if pct else None))
    chart = alt.Chart(df).mark_bar(cornerRadiusEnd=3).encode(
        enc_val(f"{y}:Q", axis=axis, scale=alt.Scale(domain=[0, 100]) if pct else alt.Undefined),
        enc_cat(f"{x}:N", sort="-x" if horizontal else None, title=None),
        color=alt.Color(f"{color}:N", scale=alt.Scale(range=PALETTE), legend=alt.Legend(orient="bottom", title=None)) if color else alt.value(ACCENT),
        tooltip=list(df.columns),
    ).properties(height=height, title=title)
    st.altair_chart(chart, use_container_width=True)


def coverage_caption(m: RunMetrics) -> None:
    cov = m.coverage
    txt = f"Coverage: {cov.eligible} eligible answers from {cov.prompts} prompts x {len(cov.providers)} provider(s)"
    if cov.failed:
        txt += f"; {cov.failed} failed/malformed answers excluded ({', '.join(f'{k}: {v}' for k, v in cov.by_status.items() if k != 'ok')})"
    st.caption(txt + ". Results reflect the specific providers, prompts and time of this run; they do not represent all consumer AI search experiences.")


def short_pid(pid: str) -> str:
    return pid.split(":")[-1]
