"""Monitoring run execution.

``run_monitoring`` sends each approved prompt to each selected provider, stores the raw
response immediately (append-only), then runs deterministic extraction and persists it.
Provider failures are recorded as non-``ok`` responses; the run finishes as ``partial``
instead of aborting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from brandorbit.analysis.extraction import extract_deterministic
from brandorbit.core.config import Settings, get_settings
from brandorbit.core.schemas import MonitoringRun, Prompt, PromptStatus, RawResponse, ResponseStatus, SourceKind, Workspace, utcnow
from brandorbit.providers.base import Provider
from brandorbit.storage.repository import Repository, new_id

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int, str], None]


class RunLimitError(ValueError):
    pass


def run_monitoring(
    repo: Repository,
    workspace: Workspace,
    providers: list[Provider],
    *,
    prompts: Optional[list[Prompt]] = None,
    label: str = "",
    run_id: Optional[str] = None,
    started_at: Optional[datetime] = None,
    finished_at: Optional[datetime] = None,
    notes: str = "",
    settings: Optional[Settings] = None,
    progress: Optional[ProgressFn] = None,
) -> MonitoringRun:
    settings = settings or get_settings()
    prompts = prompts if prompts is not None else repo.list_prompts(workspace.id, PromptStatus.approved)
    if not prompts:
        raise RunLimitError("No approved prompts to monitor.")
    if len(prompts) > settings.max_prompts_per_run:
        raise RunLimitError(f"{len(prompts)} prompts exceed the per-run limit of {settings.max_prompts_per_run}.")
    total_calls = len(prompts) * len(providers)
    if total_calls > settings.max_calls_per_run:
        raise RunLimitError(f"{total_calls} provider calls exceed the per-run limit of {settings.max_calls_per_run}.")
    if not providers:
        raise RunLimitError("Select at least one provider.")

    mode = SourceKind.live if all(p.is_live for p in providers) else SourceKind.demo_fixture
    run = MonitoringRun(
        id=run_id or new_id("run"), workspace_id=workspace.id, label=label or f"Run {utcnow():%Y-%m-%d %H:%M} UTC",
        providers=[p.id for p in providers], mode=mode, status="running", notes=notes,
        prompt_ids=[p.id for p in prompts], started_at=started_at or utcnow(),
    )
    repo.save_run(run)
    products = repo.list_products(workspace.id)
    failures = 0
    done = 0
    for prompt in prompts:
        for provider in providers:
            done += 1
            if progress:
                progress(done, total_calls, f"{provider.id}: {prompt.text[:60]}")
            result = provider.answer(prompt.text, prompt_id=prompt.id, run_id=run.id, country=workspace.brand.country, currency=workspace.brand.currency)
            resp = RawResponse(
                id=new_id("resp"), run_id=run.id, prompt_id=prompt.id, provider=provider.id, model=result.model or provider.model,
                text=result.text, citations=result.citations, status=result.status, error=result.error, latency_ms=result.latency_ms,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens, source_kind=result.source_kind,
                created_at=started_at or utcnow(),
            )
            repo.add_response(resp)
            repo.log_provider_call(run.id, provider.id, resp.model, resp.status.value, resp.latency_ms, resp.input_tokens, resp.output_tokens, resp.error)
            if resp.status != ResponseStatus.ok:
                failures += 1
                log.warning("provider %s failed for %s: %s", provider.id, prompt.id, resp.error)
            repo.save_extraction(extract_deterministic(resp, workspace, products, new_id("ext")))
    run.finished_at = finished_at or utcnow()
    run.status = "failed" if failures == total_calls else ("partial" if failures else "completed")
    return repo.save_run(run)


def rerun_extraction(repo: Repository, workspace: Workspace, run_id: str) -> int:
    """Re-run deterministic extraction over stored raw responses (raw answers are untouched)."""
    products = repo.list_products(workspace.id)
    n = 0
    for resp in repo.list_responses(run_id):
        repo.save_extraction(extract_deterministic(resp, workspace, products, new_id("ext")))
        n += 1
    return n
