"""Loads the clearly-labelled demo workspace (brand, catalogue, prompts, two fixture runs)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from brandorbit.analysis.recommendations import generate_findings
from brandorbit.core.catalogue import parse_catalogue_csv
from brandorbit.core.schemas import FindingStatus, Prompt, PromptCategory, PromptStatus, Workspace
from brandorbit.monitoring.runner import run_monitoring
from brandorbit.providers.demo import DemoProvider, demo_provider_ids, load_fixture
from brandorbit.storage.repository import Repository

DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"
DEMO_WORKSPACE_ID = "ws_demo_seraj"


def demo_workspace() -> Workspace:
    with open(DEMO_DIR / "workspace.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    raw.pop("_notice", None)
    return Workspace.model_validate(raw)


def demo_prompts(ws_id: str) -> list[Prompt]:
    with open(DEMO_DIR / "prompts.json", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [
        Prompt(id=f"{ws_id}:{p['id']}", workspace_id=ws_id, text=p["text"], category=PromptCategory(p["category"]), status=PromptStatus.approved, origin="demo")
        for p in raw["prompts"]
    ]


def ensure_demo_workspace(repo: Repository, force: bool = False) -> Workspace:
    """Create the demo workspace with both fixture runs if it does not exist yet."""
    existing = repo.get_workspace(DEMO_WORKSPACE_ID)
    if existing and not force:
        return existing
    if existing:
        repo.delete_workspace(DEMO_WORKSPACE_ID)
    ws = demo_workspace()
    repo.save_workspace(ws)
    repo.replace_products(ws.id, parse_catalogue_csv((DEMO_DIR / "catalogue.csv").read_bytes(), ws.brand.currency))
    prompts = demo_prompts(ws.id)
    repo.save_prompts(prompts)

    for fixture_name in ("run_baseline", "run_followup"):
        fx = load_fixture(fixture_name)
        providers = [DemoProvider(pid, fixture_name) for pid in demo_provider_ids(fixture_name)]
        # fixture prompt ids are short (p01); workspace prompt ids are namespaced
        for p in providers:
            p._answers = {(f"{ws.id}:{pid}", prov): v for (pid, prov), v in p._answers.items()}
        run = run_monitoring(
            repo, ws, providers, prompts=prompts, label=fx["run"]["label"], run_id=fx["run"]["id"],
            started_at=datetime.fromisoformat(fx["run"]["started_at"]), finished_at=datetime.fromisoformat(fx["run"]["finished_at"]),
            notes=fx["run"]["notes"],
        )
        generate_findings(repo, ws, run.id)
        if fixture_name == "run_baseline":
            repo.set_baseline(ws.id, run.id)
            implemented = set(load_fixture("run_followup").get("implemented_between_runs", []))
            for f in repo.list_findings(ws.id, run.id):
                if f.finding_id in implemented:
                    repo.update_finding_status(f.id, FindingStatus.completed)
    return repo.get_workspace(ws.id)
