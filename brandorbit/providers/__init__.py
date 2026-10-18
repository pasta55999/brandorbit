"""Provider registry: decides which adapters are available from the environment."""

from __future__ import annotations

from brandorbit.core.config import Settings, get_settings
from brandorbit.providers.base import Provider, ProviderResult
from brandorbit.providers.demo import DemoProvider, demo_provider_ids


def available_providers(settings: Settings | None = None, fixture_name: str = "run_baseline") -> dict[str, Provider]:
    """Live adapters when keys are configured; demo fixture providers always available."""
    settings = settings or get_settings()
    providers: dict[str, Provider] = {}
    if settings.openai_api_key:
        from brandorbit.providers.openai_provider import OpenAIProvider

        providers["openai"] = OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.request_timeout_s, settings.max_retries)
    if settings.anthropic_api_key:
        from brandorbit.providers.anthropic_provider import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model, settings.request_timeout_s, settings.max_retries)
    for pid in demo_provider_ids(fixture_name):
        providers[pid] = DemoProvider(pid, fixture_name)
    return providers


def first_live_provider(settings: Settings | None = None) -> Provider | None:
    provs = available_providers(settings)
    return next((p for p in provs.values() if p.is_live), None)


__all__ = ["Provider", "ProviderResult", "DemoProvider", "available_providers", "first_live_provider"]
