"""Renders every page headlessly with Streamlit's AppTest against a temp database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["pages_overview", "pages_visibility", "pages_competitors", "pages_perception", "pages_citations",
         "pages_recommendations", "pages_monitoring", "pages_settings"]


@pytest.fixture(scope="module", autouse=True)
def _tmp_db(tmp_path_factory):
    os.environ["BRANDORBIT_DB"] = str(tmp_path_factory.mktemp("db") / "ui.db")
    yield
    os.environ.pop("BRANDORBIT_DB", None)


def _page(module: str) -> AppTest:
    script = f"""
import streamlit as st
from brandorbit.ui import {module} as page
from brandorbit.ui.common import inject_css, sidebar_header, sidebar_footer
inject_css(); sidebar_header()
page.render()
sidebar_footer()
"""
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    return at


@pytest.mark.parametrize("module", PAGES)
def test_page_renders_without_exception(module: str):
    at = _page(module)
    assert not at.exception, [e.value for e in at.exception]


def test_entrypoint_runs():
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_overview_shows_stored_metrics_not_placeholders():
    at = _page("pages_overview")
    html = "\n".join(m.value for m in at.markdown)
    # KPI values come from the follow-up fixture run (latest run is selected by default)
    assert "63.3%" in html and "19/30" in html  # mention rate and its sample size
    assert "Priority insight" in html and "Next actions" in html
    assert "Demo mode" in html


def test_recommendation_status_change_persists():
    at = _page("pages_recommendations")
    sel = next(s for s in at.selectbox if s.key and s.key.startswith("st_"))
    assert sel.value == "open"
    sel.set_value("planned").run()
    assert not at.exception
    again = _page("pages_recommendations")
    assert next(s for s in again.selectbox if s.key == sel.key).value == "planned"


def test_run_selector_switches_period():
    at = _page("pages_overview")
    runs = at.selectbox(key="run_select")
    assert len(runs.options) == 2
    runs.select_index(1).run()
    html = "\n".join(m.value for m in at.markdown)
    assert "53.1%" in html and "17/32" in html  # baseline run figures
