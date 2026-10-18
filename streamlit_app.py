"""BrandOrbit - Streamlit entry point. Run with: streamlit run streamlit_app.py"""

from __future__ import annotations

import streamlit as st

from brandorbit.ui import (
    pages_audit,
    pages_citations,
    pages_compare,
    pages_competitors,
    pages_overview,
    pages_perception,
    pages_prompts,
    pages_recommendations,
    pages_settings,
    pages_visibility,
)
from brandorbit.ui.common import inject_css, mode_badge, sidebar_header

st.set_page_config(page_title="BrandOrbit - AI search visibility", page_icon=":material/orbit:", layout="wide", initial_sidebar_state="expanded")
inject_css()
sidebar_header()
st.sidebar.markdown(mode_badge(), unsafe_allow_html=True)
st.sidebar.write("")

pages = {
    "Monitor": [
        st.Page(pages_overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
        st.Page(pages_visibility.render, title="Visibility", icon=":material/visibility:", url_path="visibility"),
        st.Page(pages_competitors.render, title="Competitors", icon=":material/groups:", url_path="competitors"),
        st.Page(pages_perception.render, title="Perception", icon=":material/psychology:", url_path="perception"),
        st.Page(pages_citations.render, title="Citations", icon=":material/link:", url_path="citations"),
    ],
    "Investigate": [
        st.Page(pages_prompts.render, title="Prompt explorer", icon=":material/search:", url_path="prompts"),
        st.Page(pages_recommendations.render, title="Recommendations", icon=":material/checklist:", url_path="recommendations"),
        st.Page(pages_audit.render, title="Product-data audit", icon=":material/inventory_2:", url_path="audit"),
        st.Page(pages_compare.render, title="Before & after", icon=":material/compare_arrows:", url_path="compare"),
    ],
    "Configure": [st.Page(pages_settings.render, title="Settings", icon=":material/settings:", url_path="settings")],
}
nav = st.navigation(pages, position="sidebar")
st.sidebar.markdown("---")
st.sidebar.caption("Portfolio prototype. Results reflect specific providers, prompts and times - not all consumer AI search experiences.")
nav.run()
