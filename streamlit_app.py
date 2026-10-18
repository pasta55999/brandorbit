"""BrandOrbit - Streamlit entry point. Run with: streamlit run streamlit_app.py"""

from __future__ import annotations

import streamlit as st

from brandorbit.ui import (
    pages_citations,
    pages_competitors,
    pages_monitoring,
    pages_overview,
    pages_perception,
    pages_recommendations,
    pages_settings,
    pages_visibility,
)
from brandorbit.ui.common import inject_css, sidebar_footer, sidebar_header

st.set_page_config(page_title="BrandOrbit", page_icon=":material/orbit:", layout="wide", initial_sidebar_state="auto")
inject_css()
sidebar_header()

pages = {
    "": [
        st.Page(pages_overview.render, title="Overview", icon=":material/space_dashboard:", default=True),
        st.Page(pages_visibility.render, title="AI Visibility", icon=":material/visibility:", url_path="visibility"),
        st.Page(pages_competitors.render, title="Competitors", icon=":material/groups:", url_path="competitors"),
        st.Page(pages_perception.render, title="Brand Perception", icon=":material/sentiment_satisfied:", url_path="perception"),
        st.Page(pages_citations.render, title="Sources & Citations", icon=":material/link:", url_path="sources"),
        st.Page(pages_recommendations.render, title="Recommendations", icon=":material/checklist:", url_path="recommendations"),
        st.Page(pages_monitoring.render, title="Monitoring", icon=":material/monitoring:", url_path="monitoring"),
    ],
    "Workspace": [st.Page(pages_settings.render, title="Settings", icon=":material/settings:", url_path="settings")],
}
nav = st.navigation(pages, position="sidebar")
nav.run()
sidebar_footer()
