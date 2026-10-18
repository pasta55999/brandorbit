"""OpenAI adapter using the Responses API with the hosted web search tool.

Only constructed when ``OPENAI_API_KEY`` is set. Network errors, timeouts and rate limits
are converted into non-``ok`` ``ProviderResult`` statuses after bounded retries.
"""

from __future__ import annotations

import logging
from typing import Optional

from brandorbit.core.schemas import Citation, ResponseStatus, SourceKind
from brandorbit.providers.base import SYSTEM_PROMPT, Provider, ProviderResult, timed, with_retries

log = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    id = "openai"
    source_kind = SourceKind.live
    description = "OpenAI Responses API with web_search tool (live)"

    def __init__(self, api_key: str, model: str, timeout_s: float = 45, max_retries: int = 2, use_web_search: bool = True):
        from openai import OpenAI  # imported lazily so demo mode does not need the SDK configured

        self._client = OpenAI(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.model = model
        self.max_retries = max_retries
        self.use_web_search = use_web_search

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        import openai

        return isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError))

    def answer(self, prompt_text: str, *, prompt_id: str, run_id: str, country: str, currency: str) -> ProviderResult:
        import openai

        kwargs = dict(
            model=self.model,
            instructions=SYSTEM_PROMPT.format(country=country, currency=currency),
            input=prompt_text,
        )
        if self.use_web_search:
            kwargs["tools"] = [{"type": "web_search_preview"}]
        try:
            resp, latency = timed(lambda: with_retries(lambda: self._client.responses.create(**kwargs), retries=self.max_retries, is_retryable=self._retryable))
        except openai.APITimeoutError as exc:
            return ProviderResult(status=ResponseStatus.timeout, error=str(exc), model=self.model)
        except openai.RateLimitError as exc:
            return ProviderResult(status=ResponseStatus.rate_limited, error=str(exc), model=self.model)
        except Exception as exc:  # noqa: BLE001
            log.exception("openai call failed")
            return ProviderResult(status=ResponseStatus.error, error=f"{type(exc).__name__}: {exc}", model=self.model)

        text = getattr(resp, "output_text", "") or ""
        citations = _collect_citations(resp)
        usage = getattr(resp, "usage", None)
        status = ResponseStatus.ok if text.strip() else ResponseStatus.malformed
        return ProviderResult(
            text=text, citations=citations, status=status,
            error=None if status == ResponseStatus.ok else "Empty output_text",
            latency_ms=latency,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            model=getattr(resp, "model", self.model) or self.model,
        )

    def structured(self, system: str, user: str, schema_name: str) -> Optional[str]:
        try:
            resp = with_retries(
                lambda: self._client.responses.create(
                    model=self.model, instructions=system, input=user,
                    text={"format": {"type": "json_object"}},
                ),
                retries=self.max_retries, is_retryable=self._retryable,
            )
            return resp.output_text
        except Exception as exc:  # noqa: BLE001
            log.warning("openai structured call failed: %s", exc)
            return None


def _collect_citations(resp) -> list[Citation]:
    out: list[Citation] = []
    seen: set[str] = set()
    for item in getattr(resp, "output", []) or []:
        for part in getattr(item, "content", []) or []:
            for ann in getattr(part, "annotations", []) or []:
                if getattr(ann, "type", "") == "url_citation":
                    url = getattr(ann, "url", "")
                    if url and url not in seen:
                        seen.add(url)
                        out.append(Citation(url=url, title=getattr(ann, "title", "") or ""))
    return out
