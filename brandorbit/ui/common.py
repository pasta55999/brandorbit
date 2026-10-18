"""Shared UI building blocks: repo access, header/sidebar, KPI cards, sections, charts, evidence."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Callable, Optional

import altair as alt
import pandas as pd
import streamlit as st

from brandorbit.core.config import Settings, get_settings
from brandorbit.core.metrics import MetricValue, RunMetrics, compute_run_metrics
from brandorbit.core.schemas import MonitoringRun, SourceKind, Workspace
from brandorbit.monitoring.demo_loader import DEMO_WORKSPACE_ID, ensure_demo_workspace
from brandorbit.storage.repository import Repository
from brandorbit.ui.theme import ACCENT, BRAND_SERIES, CSS, LOGO_SVG, MUTED, SENTIMENT_COLORS

DEMO_EXPLAINER = (
    "**Demo mode.** No API key is configured, so this workspace replays hand-written fixture answers for a "
    "fictional brand. They imitate the *style* of AI shopping answers and are not outputs of any real AI system. "
    "Every metric is still computed from the stored data by the real pipeline.\n\n"
    "To monitor live providers, copy `.env.example` to `.env`, add `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, and restart."
)


# ------------------------------------------------------------------ plumbing
@st.cache_resource(show_spinner=False)
def get_repo() -> Repository:
    repo = Repository(get_settings().db_path)
    ensure_demo_workspace(repo)
    return repo


def settings() -> Settings:
    return get_settings()


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s: object) -> str:
    return html.escape(str(s))


# ------------------------------------------------------------------- sidebar
LOGO_PATH = str(Path(__file__).with_name("assets") / "logo.svg")


def sidebar_header() -> None:
    """Wordmark above the navigation (st.logo renders in the sidebar header slot)."""
    try:
        st.logo(LOGO_PATH, size="large", link=None)
    except Exception:  # pragma: no cover - AppTest or very old Streamlit
        st.sidebar.markdown(f'<div class="bo-wordmark">{LOGO_SVG}<div><span class="name">BrandOrbit</span><span class="tag">AI brand intelligence</span></div></div>', unsafe_allow_html=True)


def sidebar_footer() -> None:
    s = settings()
    st.sidebar.markdown("---")
    if s.demo_mode:
        with st.sidebar.popover("Demo mode - what does this mean?", use_container_width=True, icon=":material/science:"):
            st.markdown(DEMO_EXPLAINER)
    else:
        st.sidebar.markdown(f'<span class="bo-chip live">Live - {", ".join(s.live_providers)}</span>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="bo-note" style="padding-top:8px">Results reflect specific providers, prompts and times - not all consumer AI search experiences.</div>', unsafe_allow_html=True)


def select_workspace(repo: Repository) -> Workspace:
    wss = repo.list_workspaces()
    ids = [w.id for w in wss]
    current = st.session_state.get("workspace_id", DEMO_WORKSPACE_ID)
    if current not in ids:
        current = ids[0]
    st.sidebar.markdown('<div class="bo-note" style="padding:6px 0 2px 2px;text-transform:uppercase;letter-spacing:.08em;font-size:.66rem;font-weight:600">Workspace</div>', unsafe_allow_html=True)
    choice = st.sidebar.selectbox("Workspace", ids, index=ids.index(current), format_func=lambda i: next(w.name for w in wss if w.id == i), key="workspace_select", label_visibility="collapsed", help="Workspace")
    st.session_state["workspace_id"] = choice
    return repo.get_workspace(choice)


# -------------------------------------------------------------------- header
def run_label(r: MonitoringRun) -> str:
    flags = []
    if r.is_baseline:
        flags.append("baseline")
    if r.status == "partial":
        flags.append("partial")
    label = re.sub(r"\s*\(simulated.*?\)", "", r.label).strip()
    return f"{r.started_at:%d %b %Y} - {label}" + (f" ({', '.join(flags)})" if flags else "")


def page_header(title: str, subtitle: str = "", *, repo: Optional[Repository] = None, ws: Optional[Workspace] = None, with_run: bool = False, key: str = "run_select") -> Optional[MonitoringRun]:
    """Title row with an optional monitoring-period selector on the right. Returns the selected run."""
    left, right = st.columns([5, 2.2], vertical_alignment="bottom")
    with left:
        st.markdown(f"## {title}")
        if subtitle:
            st.markdown(f'<div class="bo-sub">{esc(subtitle)}</div>', unsafe_allow_html=True)
    run = None
    if with_run and repo and ws:
        runs = list(reversed(repo.list_runs(ws.id)))
        with right:
            if runs:
                run = st.selectbox("Monitoring run", runs, index=0, format_func=run_label, key=key, label_visibility="collapsed")
    st.write("")
    return run


def run_metrics(repo: Repository, ws: Workspace, run: MonitoringRun) -> RunMetrics:
    return compute_run_metrics(ws, repo.list_prompts(ws.id), repo.list_responses(run.id), repo.list_extractions(run.id))


def previous_run(repo: Repository, ws: Workspace, run: MonitoringRun) -> Optional[MonitoringRun]:
    runs = repo.list_runs(ws.id)
    idx = [r.id for r in runs].index(run.id)
    return runs[idx - 1] if idx > 0 else None


def coverage_line(m: RunMetrics, prev_label: Optional[str] = None) -> None:
    cov = m.coverage
    bits = [f"{cov.eligible} answers", f"{cov.prompts} prompts", f"{len(cov.providers)} provider{'s' if len(cov.providers) != 1 else ''}"]
    if cov.failed:
        bits.append(f"{cov.failed} failed and excluded")
    if prev_label:
        bits.append(f"changes vs {prev_label}")
    st.markdown(f'<div class="bo-note">{esc(" - ".join(bits))}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- components
def chip(text: str, kind: str = "neutral") -> str:
    return f'<span class="bo-chip {kind}">{esc(text)}</span>'


def delta_html(delta: Optional[float], suffix: str = " pts", *, lower_is_better: bool = False, decimals: int = 1) -> str:
    """Arrow shows the real direction; colour shows whether the change is good."""
    if delta is None:
        return ""
    if abs(delta) < 0.05:
        return '<span class="flat">no change</span>'
    good = (delta < 0) if lower_is_better else (delta > 0)
    arrow = "&#9650;" if delta > 0 else "&#9660;"
    return f'<span class="{"up" if good else "down"}">{arrow} {abs(delta):.{decimals}f}{suffix}</span>'


def kpi(label: str, value: str, *, help_text: str = "", sample: str = "", delta: Optional[float] = None, delta_suffix: str = " pts", invert: bool = False) -> None:
    d = delta_html(delta, "" if invert else delta_suffix, lower_is_better=invert, decimals=0 if invert else 1)
    meta = " ".join(x for x in [d, f"<span>n = {esc(sample)}</span>" if sample else ""] if x)
    helper = f'<span class="help" title="{esc(help_text)}">?</span>' if help_text else ""
    st.markdown(f'<div class="bo-kpi"><div class="label"><span>{esc(label)}</span>{helper}</div><div class="value">{esc(value)}</div><div class="meta">{meta}</div></div>', unsafe_allow_html=True)


def metric_kpi(label: str, m: MetricValue, prev: Optional[MetricValue] = None, help_text: str = "") -> None:
    delta = None if (prev is None or m.value is None or prev.value is None) else round(m.value - prev.value, 1)
    kpi(label, m.display, help_text=help_text or m.definition, sample=m.sample, delta=delta)


def section(title: str, side: str = "") -> None:
    st.markdown(f'<div class="bo-sec"><span class="t">{esc(title)}</span><span class="s">{esc(side)}</span></div>', unsafe_allow_html=True)


def empty_state(title: str, body: str = "") -> None:
    st.markdown(f'<div class="bo-empty"><b>{esc(title)}</b>{esc(body)}</div>', unsafe_allow_html=True)


def plain(text: str, limit: int = 320) -> str:
    """Flatten markdown-ish answer text to one line for quoting (no bold markers, bullets or line breaks)."""
    t = re.sub(r"[*_`#>]+", "", text)
    t = re.sub(r"^\s*(?:\d+[.)]|-)\s+", "", t, flags=re.M)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "..."


def quote(text: str, source: str = "") -> None:
    if not text:
        return
    src = f'<span class="src">{esc(source)}</span>' if source else ""
    st.markdown(f'<div class="bo-quote">"{esc(plain(text))}"{src}</div>', unsafe_allow_html=True)


def raw_block(title: str, text: str) -> None:
    body = esc(text).replace("\n", "<br>") if text else "<i>empty</i>"
    st.markdown(f'<div class="bo-raw"><div class="hd">{esc(title)}</div>{body}</div>', unsafe_allow_html=True)


def insight_card(kicker: str, title: str, body: str) -> None:
    st.markdown(f'<div class="bo-insight"><div class="k">{esc(kicker)}</div><div class="t">{esc(title)}</div><div class="b">{esc(body)}</div></div>', unsafe_allow_html=True)


def numbered_list(items: list[tuple[str, str]]) -> None:
    rows = "".join(f'<div class="row"><span class="n">{i}</span><div><div class="t">{esc(t)}</div><div class="d">{esc(d)}</div></div></div>' for i, (t, d) in enumerate(items, 1))
    st.markdown(f'<div class="bo-list">{rows}</div>', unsafe_allow_html=True)


def short_pid(pid: str) -> str:
    return pid.split(":")[-1]


def source_tag(kind: SourceKind) -> str:
    return chip("Demo fixture", "demo") if kind == SourceKind.demo_fixture else chip("Live", "live")


# -------------------------------------------------------------------- charts
def chart(c: alt.Chart) -> None:
    st.altair_chart(c, use_container_width=True, theme=None)


def hbar(df: pd.DataFrame, cat: str, val: str, *, color: Optional[str] = None, domain: Optional[list[str]] = None, pct: bool = True, height: int = 200, tooltip: Optional[list] = None, sort: Optional[list] = None) -> None:
    if df.empty:
        empty_state("No data for this view")
        return
    x = alt.X(f"{val}:Q", title=None, axis=alt.Axis(format="d", labelExpr="datum.value + '%'") if pct else alt.Axis(format="d"), scale=alt.Scale(domain=[0, 100]) if pct else alt.Undefined)
    enc = dict(x=x, y=alt.Y(f"{cat}:N", title=None, sort=sort or "-x"), tooltip=tooltip or list(df.columns))
    if color:
        enc["color"] = alt.Color(f"{color}:N", scale=alt.Scale(domain=domain, range=BRAND_SERIES) if domain else alt.Undefined, legend=None)
    else:
        enc["color"] = alt.value(ACCENT)
    chart(alt.Chart(df).mark_bar(size=16).encode(**enc).properties(height=height))


def grouped_bar(df: pd.DataFrame, group: str, val: str, series: str, domain: list[str], *, height: int = 220, pct: bool = True) -> None:
    if df.empty:
        empty_state("No data for this view")
        return
    groups = list(dict.fromkeys(df[group].tolist()))
    c = alt.Chart(df).mark_bar(size=9).encode(
        y=alt.Y(f"{group}:N", title=None, sort=groups, axis=alt.Axis(labelPadding=8)),
        yOffset=alt.YOffset(f"{series}:N", sort=domain),
        x=alt.X(f"{val}:Q", title=None, scale=alt.Scale(domain=[0, 100]) if pct else alt.Undefined, axis=alt.Axis(labelExpr="datum.value + '%'") if pct else alt.Axis()),
        color=alt.Color(f"{series}:N", scale=alt.Scale(domain=domain, range=BRAND_SERIES), legend=alt.Legend(orient="bottom", columns=4)),
        tooltip=list(df.columns),
    ).properties(height=max(height, (12 * len(domain) + 16) * len(groups)))
    chart(c)


def trend(df: pd.DataFrame, x: str, y: str, series: str, *, height: int = 240, colors: Optional[list[str]] = None) -> None:
    order = list(dict.fromkeys(df[x].tolist()))  # keep chronological order of the data
    c = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X(f"{x}:O", title=None, sort=order, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{y}:Q", title=None, scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(labelExpr="datum.value + '%'")),
        color=alt.Color(f"{series}:N", scale=alt.Scale(range=colors or BRAND_SERIES), legend=alt.Legend(orient="bottom")),
        tooltip=list(df.columns),
    ).properties(height=height)
    chart(c)


def sentiment_bar(counts: dict[str, int], height: int = 56) -> None:
    total = sum(counts.values())
    if not total:
        empty_state("No brand mentions to classify")
        return
    order = ["positive", "neutral", "uncertain", "negative"]
    df = pd.DataFrame([{"sentiment": k, "count": v, "share": round(100 * v / total, 1), "rank": order.index(k)} for k, v in counts.items() if v])
    c = alt.Chart(df).mark_bar(size=22).encode(
        x=alt.X("sum(share):Q", stack="normalize", axis=None),
        color=alt.Color("sentiment:N", scale=alt.Scale(domain=order, range=[SENTIMENT_COLORS[o] for o in order]), legend=alt.Legend(orient="bottom")),
        order=alt.Order("rank:Q"),
        tooltip=["sentiment", "count", "share"],
    ).properties(height=height)
    chart(c)


def df_table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def pct_col(label: str, **kw):
    return st.column_config.ProgressColumn(label, format="%.0f%%", min_value=0, max_value=100, **kw)


def guard_run(repo: Repository, ws: Workspace, run: Optional[MonitoringRun], render_if_missing: Optional[Callable] = None) -> bool:
    if run is not None:
        return True
    empty_state("No monitoring runs yet", "Open Monitoring to approve prompts and start a run. Demo providers work without an API key.")
    if render_if_missing:
        render_if_missing()
    return False
