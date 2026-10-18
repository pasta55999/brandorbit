"""Anthropic adapter using the Messages API with the server-side web search tool."""

from __future__ import annotations

import logging
from typing import Optional

from brandorbit.core.schemas import Citation, ResponseStatus, SourceKind
from brandorbit.providers.base import SYSTEM_PROMPT, Provider, ProviderResult, timed, with_retries

log = logging.getLogger(__name__)


class AnthropicProvider(Provider):
    id = "anthropic"
    source_kind = SourceKind.live
    description = "Anthropic Messages API with web_search tool (live)"

    def __init__(self, api_key: str, model: str, timeout_s: float = 45, max_retries: int = 2, use_web_search: bool = True):
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.model = model
        self.max_retries = max_retries
        self.use_web_search = use_web_search

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        import anthropic

        return isinstance(exc, (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.InternalServerError))

    def answer(self, prompt_text: str, *, prompt_id: str, run_id: str, country: str, currency: str) -> ProviderResult:
        import anthropic

        kwargs = dict(
            model=self.model, max_tokens=1024,
            system=SYSTEM_PROMPT.format(country=country, currency=currency),
            messages=[{"role": "user", "content": prompt_text}],
        )
        if self.use_web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
        try:
            msg, latency = timed(lambda: with_retries(lambda: self._client.messages.create(**kwargs), retries=self.max_retries, is_retryable=self._retryable))
        except anthropic.APITimeoutError as exc:
            return ProviderResult(status=ResponseStatus.timeout, error=str(exc), model=self.model)
        except anthropic.RateLimitError as exc:
            return ProviderResult(status=ResponseStatus.rate_limited, error=str(exc), model=self.model)
        except Exception as exc:  # noqa: BLE001
            log.exception("anthropic call failed")
            return ProviderResult(status=ResponseStatus.error, error=f"{type(exc).__name__}: {exc}", model=self.model)

        text_parts, citations, seen = [], [], set()
        for block in msg.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
                for c in getattr(block, "citations", None) or []:
                    url = getattr(c, "url", "")
                    if url and url not in seen:
                        seen.add(url)
                        citations.append(Citation(url=url, title=getattr(c, "title", "") or ""))
        text = "".join(text_parts)
        status = ResponseStatus.ok if text.strip() else ResponseStatus.malformed
        usage = getattr(msg, "usage", None)
        return ProviderResult(
            text=text, citations=citations, status=status, error=None if status == ResponseStatus.ok else "Empty text content",
            latency_ms=latency, input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
            model=getattr(msg, "model", self.model) or self.model,
        )

    def structured(self, system: str, user: str, schema_name: str) -> Optional[str]:
        try:
            msg = with_retries(
                lambda: self._client.messages.create(
                    model=self.model, max_tokens=2048, system=system + "\nRespond with a single JSON object and nothing else.",
                    messages=[{"role": "user", "content": user}, {"role": "assistant", "content": "{"}],
                ),
                retries=self.max_retries, is_retryable=self._retryable,
            )
            return "{" + "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        except Exception as exc:  # noqa: BLE001
            log.warning("anthropic structured call failed: %s", exc)
            return None
