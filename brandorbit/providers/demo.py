"""Demo fixture provider.

Replays hand-written fixture answers from ``data/demo/fixtures``. Results are always tagged
``source_kind=demo_fixture`` so the UI can label them. For prompts that have no fixture
(e.g. user-added prompts in a demo workspace) the provider returns a clearly marked
``error`` result rather than inventing an answer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from brandorbit.core.schemas import Citation, ResponseStatus, SourceKind
from brandorbit.providers.base import Provider, ProviderResult

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "demo" / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / f"{name}.json", encoding="utf-8") as fh:
        fx = json.load(fh)
    if "providers" not in fx:  # follow-up fixtures inherit provider metadata from the baseline
        fx["providers"] = load_fixture("run_baseline")["providers"]
    return fx


def _resolve(fixture: dict, baseline: Optional[dict]) -> dict[tuple[str, str], dict]:
    """Expand ``same_as_baseline`` entries into concrete answers."""
    base = {(r["prompt_id"], r["provider"]): r for r in (baseline or {}).get("responses", [])}
    out = {}
    for r in fixture["responses"]:
        key = (r["prompt_id"], r["provider"])
        out[key] = base[key] if r.get("same_as_baseline") else r
    return out


class DemoProvider(Provider):
    source_kind = SourceKind.demo_fixture

    def __init__(self, provider_id: str, fixture_name: str = "run_baseline"):
        self.id = provider_id
        self.fixture_name = fixture_name
        fixture = load_fixture(fixture_name)
        baseline = load_fixture("run_baseline") if fixture_name != "run_baseline" else None
        meta = fixture["providers"][provider_id]
        self.model = meta["model"]
        self.description = meta["description"] + " [DEMO FIXTURE]"
        self._answers = {k: v for k, v in _resolve(fixture, baseline).items() if k[1] == provider_id}

    def answer(self, prompt_text: str, *, prompt_id: str, run_id: str, country: str, currency: str) -> ProviderResult:
        fx = self._answers.get((prompt_id, self.id))
        if fx is None:
            return ProviderResult(
                status=ResponseStatus.error,
                error="No demo fixture exists for this prompt. Demo mode never fabricates answers; configure a live provider to monitor new prompts.",
                latency_ms=0, model=self.model, source_kind=self.source_kind,
            )
        return ProviderResult(
            text=fx.get("text", ""),
            citations=[Citation(**c) for c in fx.get("citations", [])],
            status=ResponseStatus(fx.get("status", "ok")),
            error=fx.get("error"),
            latency_ms=fx.get("latency_ms"),
            input_tokens=None,
            output_tokens=None,
            model=self.model,
            source_kind=self.source_kind,
        )


def demo_provider_ids(fixture_name: str = "run_baseline") -> list[str]:
    return list(load_fixture(fixture_name)["providers"].keys())
