from __future__ import annotations

import pytest

from brandorbit.core.catalogue import parse_catalogue_csv
from brandorbit.monitoring.demo_loader import DEMO_DIR, demo_workspace, ensure_demo_workspace
from brandorbit.storage.repository import Repository


@pytest.fixture
def ws():
    return demo_workspace()


@pytest.fixture
def products():
    return parse_catalogue_csv((DEMO_DIR / "catalogue.csv").read_bytes())


@pytest.fixture
def repo():
    r = Repository(":memory:")
    yield r
    r.close()


@pytest.fixture
def demo_repo():
    r = Repository(":memory:")
    ensure_demo_workspace(r)
    yield r
    r.close()
