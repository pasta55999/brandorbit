"""Pydantic schemas shared across storage, analysis and UI.

Design notes
- Raw provider responses (`RawResponse`) are immutable once stored; extracted data
  (`Extraction`) is stored separately and can be regenerated.
- Every analytical object carries enough identifiers (response_id, prompt_id) to be
  traced back to the raw evidence it was derived from.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def domain_of(url: str) -> str:
    """Return the registrable-ish host of a URL (lowercase, without `www.`)."""
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# --------------------------------------------------------------------------- enums
class PromptCategory(str, Enum):
    discovery = "discovery"
    comparison = "comparison"
    product_specific = "product_specific"
    problem_solving = "problem_solving"
    purchase_intent = "purchase_intent"


class PromptStatus(str, Enum):
    suggested = "suggested"
    approved = "approved"
    archived = "archived"


class ResponseStatus(str, Enum):
    ok = "ok"
    error = "error"
    timeout = "timeout"
    rate_limited = "rate_limited"
    malformed = "malformed"


class SourceKind(str, Enum):
    live = "live"
    demo_fixture = "demo_fixture"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    uncertain = "uncertain"


class VerificationStatus(str, Enum):
    verified = "verified"
    conflict = "conflict"
    unverifiable = "unverifiable"
    inconclusive = "inconclusive"


class Severity(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class FindingStatus(str, Enum):
    open = "open"
    planned = "planned"
    completed = "completed"
    dismissed = "dismissed"


# ------------------------------------------------------------------- workspace
class Competitor(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    website: str = ""
    aliases: list[str] = Field(default_factory=list)

    @field_validator("website")
    @classmethod
    def _norm_site(cls, v: str) -> str:
        return normalise_url(v) if v else ""

    @property
    def domain(self) -> str:
        return domain_of(self.website)


class BrandProfile(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    website: str
    industry: str = Field(min_length=1, max_length=120)
    categories: list[str] = Field(default_factory=list)
    country: str = "United Arab Emirates"
    country_code: str = "AE"
    currency: str = "AED"
    language: str = "en"
    aliases: list[str] = Field(default_factory=list)
    description: str = ""

    @field_validator("website")
    @classmethod
    def _norm_site(cls, v: str) -> str:
        return normalise_url(v)

    @property
    def domain(self) -> str:
        return domain_of(self.website)


class Workspace(BaseModel):
    id: str
    name: str
    brand: BrandProfile
    competitors: list[Competitor] = Field(default_factory=list)
    is_demo: bool = False
    created_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _unique_names(self) -> "Workspace":
        names = [self.brand.name.lower()] + [c.name.lower() for c in self.competitors]
        if len(set(names)) != len(names):
            raise ValueError("Brand and competitor names must be unique")
        return self

    def all_brands(self) -> list[str]:
        return [self.brand.name] + [c.name for c in self.competitors]


class Product(BaseModel):
    sku: str
    name: str
    category: str = ""
    price: Optional[float] = None
    currency: str = "AED"
    description: str = ""
    url: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------- prompts
class Prompt(BaseModel):
    id: str
    workspace_id: str
    text: str = Field(min_length=8, max_length=500)
    category: PromptCategory
    language: str = "en"
    status: PromptStatus = PromptStatus.approved
    origin: Literal["manual", "llm_suggested", "demo"] = "manual"
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------- responses
class Citation(BaseModel):
    url: str
    title: str = ""

    @property
    def domain(self) -> str:
        return domain_of(self.url)


class RawResponse(BaseModel):
    """Immutable record of what a provider returned for a prompt."""

    id: str
    run_id: str
    prompt_id: str
    provider: str
    model: str
    text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    status: ResponseStatus = ResponseStatus.ok
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    source_kind: SourceKind = SourceKind.demo_fixture
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def is_eligible(self) -> bool:
        """Only successful, non-empty answers count towards metrics."""
        return self.status == ResponseStatus.ok and bool(self.text.strip())


class MonitoringRun(BaseModel):
    id: str
    workspace_id: str
    label: str = ""
    providers: list[str] = Field(default_factory=list)
    mode: SourceKind = SourceKind.demo_fixture
    status: Literal["running", "completed", "partial", "failed"] = "completed"
    is_baseline: bool = False
    notes: str = ""
    prompt_ids: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


# ------------------------------------------------------------------ extraction
class Mention(BaseModel):
    brand: str
    is_target: bool
    position: int = Field(ge=1, description="Order of first appearance among detected brands")
    list_rank: Optional[int] = Field(default=None, description="Rank in a numbered list if present")
    recommended: bool = False
    sentiment: Sentiment = Sentiment.uncertain
    evidence_quote: str = ""
    attributes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)


class ProductClaim(BaseModel):
    brand: str
    product: Optional[str] = None
    attribute: str
    claimed_value: str
    quote: str
    trusted_value: Optional[str] = None
    verification_status: VerificationStatus = VerificationStatus.unverifiable
    confidence: float = Field(ge=0, le=1, default=0.5)


class Extraction(BaseModel):
    id: str
    response_id: str
    method: Literal["deterministic", "llm", "naive"] = "deterministic"
    mentions: list[Mention] = Field(default_factory=list)
    claims: list[ProductClaim] = Field(default_factory=list)
    cited_domains: list[str] = Field(default_factory=list)
    target_mentioned: bool = False
    target_cited: bool = False
    target_sentiment: Sentiment = Sentiment.uncertain
    confidence: float = Field(ge=0, le=1, default=0.5)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class LLMExtractionOutput(BaseModel):
    """Schema the LLM-assisted extractor must return. Validated with Pydantic."""

    mentions: list[Mention]
    claims: list[ProductClaim] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0, le=1)

    @field_validator("mentions")
    @classmethod
    def _quotes_required(cls, v: list[Mention]) -> list[Mention]:
        for m in v:
            if not m.evidence_quote.strip():
                raise ValueError(f"Mention of {m.brand} lacks an evidence quote")
        return v


# -------------------------------------------------------------------- findings
class Evidence(BaseModel):
    prompt_id: str
    response_id: str
    quote: str = ""
    source_url: Optional[str] = None


class Finding(BaseModel):
    id: str
    workspace_id: str
    run_id: str
    finding_id: str = Field(pattern=r"^F-[A-Z]{2,4}-\d{3}$")
    category: Literal[
        "visibility_gap",
        "competitor_gap",
        "inaccurate_claim",
        "citation_gap",
        "catalogue_gap",
        "perception",
        "source_quality",
    ]
    severity: Severity
    title: str
    explanation: str
    proposed_action: str
    expected_outcome: str = Field(description="Hypothesis, not a guarantee")
    evidence: list[Evidence] = Field(default_factory=list)
    source_url: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    limitations: str = ""
    verification_status: VerificationStatus = VerificationStatus.inconclusive
    status: FindingStatus = FindingStatus.open
    related_prompt_ids: list[str] = Field(default_factory=list)
    generated_by: Literal["rules", "rules+llm"] = "rules"
    created_at: datetime = Field(default_factory=utcnow)


class LLMFindingNarrative(BaseModel):
    """Optional LLM enrichment of a rule-generated finding."""

    finding_id: str
    explanation: str = Field(max_length=1200)
    proposed_action: str = Field(max_length=800)
    expected_outcome: str = Field(max_length=600)
    confidence: float = Field(ge=0, le=1)
    quotes_used: list[str] = Field(default_factory=list)


class SuggestedPrompt(BaseModel):
    text: str = Field(min_length=8, max_length=300)
    category: PromptCategory


class SuggestedPromptSet(BaseModel):
    prompts: list[SuggestedPrompt] = Field(max_length=40)


# ----------------------------------------------------------------- validation
_URL_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(/.*)?$", re.I)


def normalise_url(value: str) -> str:
    """Accept `example.ae`, `www.example.ae` or a full URL; return `https://host/path`."""
    v = value.strip()
    if not v:
        raise ValueError("URL is required")
    if "://" not in v:
        v = "https://" + v
    parsed = urlparse(v)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or "." not in parsed.hostname:
        raise ValueError(f"Invalid website URL: {value!r}")
    if not _URL_RE.match(parsed.hostname + (parsed.path or "")):
        raise ValueError(f"Invalid website URL: {value!r}")
    HttpUrl(v)
    return v.rstrip("/")


def to_jsonable(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
