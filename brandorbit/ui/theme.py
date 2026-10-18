"""Visual identity: palette, global CSS and the Altair chart theme.

One accent (forest green), warm neutrals, near-black type. Everything else is grey.
"""

from __future__ import annotations

import altair as alt

BG = "#FAFAF7"
SURFACE = "#FFFFFF"
SURFACE_2 = "#F2F1EC"
BORDER = "#E6E4DD"
TEXT = "#15181E"
MUTED = "#6B7280"
FAINT = "#9CA3AF"
ACCENT = "#1F6F5B"
ACCENT_SOFT = "#E4F0EC"
NEG = "#B3432E"
NEG_SOFT = "#F8E7E3"
WARN = "#9A6A12"
WARN_SOFT = "#F7EEDC"
INFO_SOFT = "#E9EDF5"
INFO = "#3B5580"

# target brand first, competitors in muted neutrals so the brand always stands out
BRAND_SERIES = [ACCENT, "#8E9AA6", "#B9AE9A", "#7C98AA", "#A99BB8", "#C4A28A", "#8FAE9D"]
SENTIMENT_COLORS = {"positive": ACCENT, "neutral": "#A3ADB8", "negative": NEG, "uncertain": "#D3C7A8"}
SEVERITY_COLORS = {"high": NEG, "medium": WARN, "low": INFO}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, .stApp, .stMarkdown, .stDataFrame, button, input, textarea, select {{ font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }}
[data-testid="stIconMaterial"], .material-symbols-rounded {{ font-family: 'Material Symbols Rounded' !important; }}
.stApp {{ background: {BG}; }}
.block-container {{ padding: 1.4rem 2.4rem 3rem 2.4rem; max-width: 1240px; }}
@media (max-width: 900px) {{ .block-container {{ padding: 3.4rem 1rem 2rem 1rem; }} }}
h1, h2, h3, h4 {{ color: {TEXT}; letter-spacing: -0.01em; }}
h2 {{ font-size: 1.45rem !important; font-weight: 600 !important; margin-bottom: 0 !important; padding-bottom: 0 !important; }}
h4 {{ font-size: 0.95rem !important; font-weight: 600 !important; margin: 0 0 .35rem 0 !important; padding: 0 !important; }}
p, li {{ color: {TEXT}; }}
a {{ color: {ACCENT}; }}
hr {{ border-color: {BORDER}; margin: 1.2rem 0; }}

/* sidebar */
section[data-testid="stSidebar"] {{ background: {SURFACE_2}; border-right: 1px solid {BORDER}; }}
section[data-testid="stSidebar"] .block-container {{ padding: 1rem 0.9rem; }}
section[data-testid="stSidebar"] a {{ color: {TEXT} !important; border-radius: 8px; font-size: .9rem; }}
section[data-testid="stSidebar"] a[aria-current="page"] {{ background: {ACCENT_SOFT} !important; }}
section[data-testid="stSidebar"] a[aria-current="page"] span {{ color: {ACCENT} !important; font-weight: 600; }}
section[data-testid="stSidebar"] a:hover {{ background: #E9E8E2 !important; }}
section[data-testid="stSidebar"] [data-testid="stNavSectionHeader"] {{ color: {FAINT}; font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; font-weight: 600; padding-top: .6rem; }}
.bo-wordmark {{ display:flex; align-items:center; gap:9px; padding: 2px 4px 10px 4px; }}
.bo-wordmark .name {{ font-weight: 700; font-size: 1.02rem; color: {TEXT}; letter-spacing: -0.01em; }}
.bo-wordmark .tag {{ font-size: .7rem; color: {MUTED}; display:block; margin-top:-2px; }}

/* chips & badges */
.bo-chip {{ display:inline-flex; align-items:center; gap:6px; padding: 2px 9px; border-radius: 999px; font-size: .72rem; font-weight: 600; border: 1px solid transparent; line-height: 1.5; white-space: nowrap; }}
.bo-chip.demo {{ background: {WARN_SOFT}; color: {WARN}; border-color: #EAD9B0; }}
.bo-chip.live {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-color: #BFDDD2; }}
.bo-chip.high {{ background: {NEG_SOFT}; color: {NEG}; }}
.bo-chip.medium {{ background: {WARN_SOFT}; color: {WARN}; }}
.bo-chip.low {{ background: {INFO_SOFT}; color: {INFO}; }}
.bo-chip.neutral {{ background: {SURFACE_2}; color: {MUTED}; }}
.bo-chip.good {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
.bo-chip.bad {{ background: {NEG_SOFT}; color: {NEG}; }}

/* KPI */
.bo-kpi {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 14px 16px 12px 16px; min-height: 104px; }}
.bo-kpi .label {{ color: {MUTED}; font-size: .76rem; font-weight: 500; display:flex; justify-content:space-between; align-items:center; }}
.bo-kpi .label .help {{ color: {FAINT}; font-size: .72rem; border: 1px solid {BORDER}; border-radius: 999px; width: 15px; height: 15px; display:inline-flex; align-items:center; justify-content:center; cursor: help; }}
.bo-kpi .value {{ color: {TEXT}; font-size: 1.75rem; font-weight: 600; line-height: 1.1; margin-top: 8px; letter-spacing: -0.02em; }}
.bo-kpi .meta {{ margin-top: 6px; min-height: 18px; font-size: .74rem; color: {MUTED}; display:flex; gap:8px; align-items:center; flex-wrap: wrap; }}
.bo-kpi .up {{ color: {ACCENT}; font-weight: 600; }}
.bo-kpi .down {{ color: {NEG}; font-weight: 600; }}
.bo-kpi .flat {{ color: {FAINT}; font-weight: 500; }}

/* section headings */
.bo-sec {{ display:flex; align-items:baseline; justify-content:space-between; margin: 1.3rem 0 .5rem 0; }}
.bo-sec .t {{ font-size: .95rem; font-weight: 600; color: {TEXT}; }}
.bo-sec .s {{ font-size: .78rem; color: {MUTED}; }}
.bo-sub {{ font-size: .82rem; color: {MUTED}; margin-top: 2px; }}

/* evidence & insight */
.bo-quote {{ border-left: 2px solid {BORDER}; padding: 4px 12px; color: #374151; font-size: .86rem; margin: 6px 0 4px 0; }}
.bo-quote .src {{ display:block; font-size: .72rem; color: {FAINT}; margin-top: 3px; font-style: normal; }}
.bo-insight {{ background: {SURFACE}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT}; border-radius: 10px; padding: 14px 18px; }}
.bo-insight .k {{ font-size: .7rem; letter-spacing: .08em; text-transform: uppercase; color: {ACCENT}; font-weight: 600; }}
.bo-insight .t {{ font-size: 1.02rem; font-weight: 600; color: {TEXT}; margin: 4px 0 6px 0; }}
.bo-insight .b {{ font-size: .86rem; color: #374151; }}
.bo-list {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px 0; }}
.bo-list .row {{ display:flex; gap:12px; align-items:flex-start; padding: 9px 16px; border-bottom: 1px solid {BORDER}; }}
.bo-list .row:last-child {{ border-bottom: none; }}
.bo-list .n {{ color: {FAINT}; font-size: .8rem; font-weight: 600; min-width: 16px; padding-top: 2px; }}
.bo-list .t {{ font-size: .88rem; font-weight: 600; color: {TEXT}; }}
.bo-list .d {{ font-size: .78rem; color: {MUTED}; margin-top: 2px; }}
.bo-empty {{ border: 1px dashed {BORDER}; border-radius: 10px; padding: 22px; text-align:center; color: {MUTED}; font-size: .86rem; background: {SURFACE}; }}
.bo-empty b {{ color: {TEXT}; display:block; margin-bottom: 4px; font-weight: 600; }}
.bo-note {{ font-size: .78rem; color: {MUTED}; }}
.bo-raw {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px; font-size: .86rem; color: #1F2937; }}
.bo-raw .hd {{ font-size: .68rem; letter-spacing: .08em; text-transform: uppercase; color: {FAINT}; font-weight: 600; margin-bottom: 6px; }}

/* streamlit widget polish */
[data-testid="stExpander"] details {{ border: 1px solid {BORDER}; border-radius: 10px; background: {SURFACE}; }}
[data-testid="stExpander"] summary {{ font-size: .88rem; }}
div[data-testid="stVerticalBlockBorderWrapper"] > div {{ border-color: {BORDER} !important; border-radius: 10px !important; background: {SURFACE}; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid {BORDER}; }}
.stTabs [data-baseweb="tab"] {{ font-size: .86rem; padding: 6px 10px; }}
.stTabs [aria-selected="true"] {{ color: {ACCENT} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {ACCENT}; }}
[data-testid="stDataFrame"] {{ border: 1px solid {BORDER}; border-radius: 10px; overflow: hidden; }}
.stButton > button {{ border-radius: 8px; font-size: .86rem; }}
[data-testid="stCaptionContainer"] p {{ color: {MUTED}; font-size: .78rem; }}
div[data-testid="stMetric"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 14px; }}
div[data-testid="stMetric"] label p {{ font-size: .76rem; color: {MUTED}; }}
</style>
"""

LOGO_SVG = f"""
<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="BrandOrbit">
<circle cx="14" cy="14" r="12.2" stroke="{BORDER}" stroke-width="1.3"/>
<ellipse cx="14" cy="14" rx="12.2" ry="5" stroke="{ACCENT}" stroke-width="1.5" transform="rotate(-28 14 14)"/>
<circle cx="14" cy="14" r="3.3" fill="{TEXT}"/>
<circle cx="23.6" cy="8.4" r="1.7" fill="{ACCENT}"/>
</svg>
"""


def altair_theme() -> dict:
    return {
        "config": {
            "background": "transparent",
            "view": {"stroke": "transparent"},
            "font": "Inter, sans-serif",
            "axis": {"labelColor": MUTED, "titleColor": MUTED, "labelFontSize": 11, "titleFontSize": 11, "gridColor": "#EEEDE7", "domainColor": BORDER, "tickColor": BORDER, "labelFontWeight": 400, "titleFontWeight": 500},
            "legend": {"labelColor": TEXT, "titleColor": MUTED, "labelFontSize": 11, "symbolSize": 70, "orient": "bottom", "title": None},
            "title": {"color": TEXT, "fontSize": 12, "fontWeight": 600, "anchor": "start"},
            "range": {"category": BRAND_SERIES},
            "bar": {"cornerRadiusEnd": 2},
            "line": {"strokeWidth": 2},
            "point": {"size": 50, "filled": True},
        }
    }


try:  # altair >= 5.5
    alt.theme.register("brandorbit", enable=True)(altair_theme)
except AttributeError:  # pragma: no cover - older altair
    alt.themes.register("brandorbit", altair_theme)
    alt.themes.enable("brandorbit")
