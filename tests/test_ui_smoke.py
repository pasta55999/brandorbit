"""Renders every page headlessly with Streamlit's AppTest against a temp database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["pages_overview", "pages_visibility", "pages_competitors", "pages_perception", "pages_citations",
         "pages_prompts", "pages_recommendations", "pages_audit", "pages_compare", "pages_settings"]


@pytest.fixture(scope="module", autouse=True)
def _tmp_db(tmp_path_factory):
    os.environ["BRANDORBIT_DB"] = str(tmp_path_factory.mktemp("db") / "ui.db")
    yield
    os.environ.pop("BRANDORBIT_DB", None)


@pytest.mark.parametrize("module", PAGES)
def test_page_renders_without_exception(module: str):
    script = f"""
import streamlit as st
from brandorbit.ui import {module} as page
from brandorbit.ui.common import inject_css, sidebar_header
inject_css(); sidebar_header()
page.render()
"""
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_entrypoint_runs():
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"), default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
