"""Deterministic extraction of brand mentions, citations, sentiment and product claims.

Two deterministic strategies are implemented so they can be compared in the evaluation:

* ``naive``          - case-insensitive substring match on the brand name only; no sentiment,
                       no claims. Serves as the floor the rule-based extractor must beat.
* ``deterministic``  - word-boundary alias matching, sentence-level evidence quotes,
                       list-rank detection, lexicon sentiment with negation/hedge handling,
                       and regex claim extraction verified against the product catalogue.

Everything here is pure Python with no network access, so it runs in demo mode and in tests.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional

from brandorbit.core.schemas import (
    Citation,
    Extraction,
    Mention,
    Product,
    ProductClaim,
    RawResponse,
    Sentiment,
    VerificationStatus,
    Workspace,
    domain_of,
)

# ----------------------------------------------------------------- lexicons
POSITIVE = {
    "best", "reliable", "dependable", "recommended", "recommend", "praised", "praise", "excellent", "great",
    "solid", "strong", "well reviewed", "well-reviewed", "good value", "best value", "quality", "responsive",
    "durable", "top", "stands out", "safest", "better", "well built", "well-built", "sturdier", "longer warranty",
    "popular", "frequently recommended", "trusted", "fast", "free",
}
NEGATIVE = {
    "overpriced", "complaints", "complaint", "poor", "unreliable", "degrades", "degrade", "shorter", "mixed",
    "average", "slow", "fails", "failed", "issue", "issues", "problem", "problems", "cheaply", "noisy",
    "limited", "weak", "only ships", "only offers", "not recommended", "avoid", "disappointing", "adequate", "basic",
}
HEDGES = {"some users", "reportedly", "according to", "may", "might", "reviews are mixed", "varies", "unclear", "occasionally"}
NEGATORS = {"not", "no", "never", "isn't", "aren't", "without", "lacks"}
RECOMMEND_CUES = {"recommend", "recommended", "best", "pick", "choice", "choose", "top", "stands out", "worth considering", "consider", "good option", "solid option", "suits", "good fit", "likely to last", "reasonable alternative"}

ATTRIBUTE_LEXICON = {
    "affordable": ["affordable", "cheaper", "cheapest", "budget", "value", "well-priced", "competitive pric"],
    "premium": ["premium", "design-led", "stylish"],
    "warranty": ["warranty"],
    "fast delivery": ["next-day delivery", "same-day delivery", "fast delivery", "quick delivery", "1-2 day delivery"],
    "wide range": ["wide range", "wider range", "broad selection", "large catalogue", "widest choice", "more models"],
    "support": ["support", "after-sales"],
    "quiet": ["quiet", "low-noise", "sound shield", "sound-dampening", "quieter"],
    "battery life": ["runtime", "battery"],
    "lightweight": ["lightweight", "lighter", "light "],
    "filtration": ["hepa", "reverse osmosis", "ro system", "5-stage", "6-stage"],
    "no installation": ["no plumbing", "no installation", "needs no"],
    "build quality": ["build quality", "well built", "sturdier", "durable"],
    "direct-to-consumer": ["direct-to-consumer", "own store", "official store"],
}

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
LIST_ITEM = re.compile(r"^\s*(?:(\d+)[.)]|[-*\u2022])\s+", re.M)
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
PRICE_RE = re.compile(r"(?:AED|USD|SAR|EUR|GBP|\$)\s?([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
WARRANTY_RE = re.compile(r"(\d+)[- ]year(?:s)?\s+warranty|warranty\s+(?:of\s+)?(\d+)\s+years?", re.I)
CAPACITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s?(?:L|litre|liter)s?\b", re.I)
POWER_RE = re.compile(r"(\d{3,4})\s?W\b")
RUNTIME_RE = re.compile(r"(\d{2,3})[- ]minute", re.I)
WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s?kg\b", re.I)


# ----------------------------------------------------------------- helpers
def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text) if s and s.strip()]


def _alias_pattern(names: Iterable[str]) -> re.Pattern:
    alts = sorted({re.escape(n) for n in names if n}, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(alts) + r")(?:'s)?(?![\w-])", re.I)


@dataclass
class BrandMatcher:
    """Compiled alias patterns for the target brand and competitors."""

    workspace: Workspace
    patterns: dict[str, re.Pattern] = field(default_factory=dict)

    def __post_init__(self) -> None:
        b = self.workspace.brand
        self.patterns[b.name] = _alias_pattern([b.name, *b.aliases, b.domain])
        for c in self.workspace.competitors:
            self.patterns[c.name] = _alias_pattern([c.name, *c.aliases, c.domain])

    def find(self, text: str) -> dict[str, list[re.Match]]:
        return {brand: list(p.finditer(text)) for brand, p in self.patterns.items() if p.search(text)}

    def brands_in(self, sentence: str) -> list[str]:
        return [b for b, p in self.patterns.items() if p.search(sentence)]


def _lexicon_hits(sentence: str, lexicon: set[str]) -> int:
    s = sentence.lower()
    return sum(1 for w in lexicon if w in s)


def _negated(sentence: str, cue: str) -> bool:
    s = sentence.lower()
    idx = s.find(cue)
    if idx < 0:
        return False
    window = s[max(0, idx - 25): idx].split()
    return any(w in NEGATORS for w in window)


def classify_sentiment(sentence_list: list[str]) -> tuple[Sentiment, float]:
    """Lexicon sentiment over the sentences that mention a brand.

    Returns (label, confidence). Hedged or mixed evidence is downgraded to ``uncertain``.
    """
    pos = neg = hedge = 0
    for s in sentence_list:
        sl = s.lower()
        for w in POSITIVE:
            if w in sl:
                neg_flip = _negated(sl, w)
                pos += 0 if neg_flip else 1
                neg += 1 if neg_flip else 0
        for w in NEGATIVE:
            if w in sl:
                neg += 1
        hedge += _lexicon_hits(sl, HEDGES)
    total = pos + neg
    if total == 0:
        return Sentiment.neutral, 0.55
    if pos > 0 and neg > 0 and abs(pos - neg) <= 1:
        return Sentiment.uncertain, 0.5
    if hedge and total <= 2:
        return Sentiment.uncertain, 0.5
    if pos > neg:
        return Sentiment.positive, min(0.95, 0.6 + 0.1 * (pos - neg))
    return Sentiment.negative, min(0.95, 0.6 + 0.1 * (neg - pos))


def detect_attributes(sentence_list: list[str]) -> list[str]:
    joined = " ".join(sentence_list).lower()
    return [attr for attr, cues in ATTRIBUTE_LEXICON.items() if any(c in joined for c in cues)]


def _list_rank(text: str, match_start: int) -> Optional[int]:
    """If the match is inside a numbered list item, return its number."""
    line_start = text.rfind("\n", 0, match_start) + 1
    line = text[line_start: text.find("\n", match_start) if text.find("\n", match_start) >= 0 else len(text)]
    m = LIST_ITEM.match(line)
    return int(m.group(1)) if m and m.group(1) else None


def _is_recommended(sentence_list: list[str]) -> bool:
    joined = " ".join(sentence_list).lower()
    if any(_negated(joined, cue) for cue in ("recommend", "recommended")):
        return False
    return any(cue in joined for cue in RECOMMEND_CUES)


# ----------------------------------------------------------------- citations
def extract_citations(resp: RawResponse) -> list[Citation]:
    seen = {c.url for c in resp.citations}
    out = list(resp.citations)
    for m in URL_RE.finditer(resp.text):
        url = m.group(0).rstrip(".,;")
        if url not in seen:
            out.append(Citation(url=url, title="(inline URL)"))
            seen.add(url)
    return out


# -------------------------------------------------------------------- claims
GENERIC_TOKENS = {"with", "and", "the", "for", "edition", "home", "pro", "mini", "compact", "glass", "cordless", "stick"}
BOUND_WORDS = re.compile(r"\b(under|below|up to|less than|within|budget of|max(?:imum)?)\s+(?:AED|USD|SAR|EUR|GBP|\$)\s?[0-9]", re.I)


def _product_tokens(p: Product, brand_words: set[str]) -> list[str]:
    return [t for t in re.split(r"[\s/,-]+", p.name.lower()) if len(t) >= 3 and t not in brand_words]


def _token_in(token: str, sentence_l: str) -> bool:
    cap = re.fullmatch(r"(\d+(?:\.\d+)?)l", token)
    pattern = rf"\b{re.escape(cap.group(1))}\s?(?:l|litre|liter)s?\b" if cap else rf"\b{re.escape(token)}\b"
    return re.search(pattern, sentence_l) is not None


def _products_in_sentence(sentence: str, products: list[Product], brand_words: set[str] = frozenset()) -> list[Product]:
    """Return the best-matching products for a sentence, most specific first.

    A product qualifies when its distinctive model token (e.g. ``aircrisp``) appears; among
    qualifying products the one with the most matched name tokens wins. Ties are returned
    together so callers can treat the match as ambiguous.
    """
    s = sentence.lower()
    scored: list[tuple[int, Product]] = []
    for p in products:
        toks = _product_tokens(p, brand_words)
        if not toks:
            continue
        distinctive = [t for t in toks if t not in GENERIC_TOKENS and not re.fullmatch(r"\d+(?:\.\d+)?l", t)]
        if not distinctive or not _token_in(distinctive[0], s):
            continue
        score = sum(1 for t in toks if _token_in(t, s))
        scored.append((score, p))
    if not scored:
        return []
    best = max(sc for sc, _ in scored)
    return [p for sc, p in scored if sc == best]


def _is_bounded_price(sentence: str, match: re.Match) -> bool:
    """True when the price is a budget bound ("under AED 600"), not a product price."""
    return any(b.end() >= match.start() >= b.start() for b in BOUND_WORDS.finditer(sentence))


def _verify(attribute: str, claimed: str, product: Optional[Product]) -> tuple[Optional[str], VerificationStatus]:
    if product is None:
        return None, VerificationStatus.unverifiable
    if attribute == "price":
        if product.price is None:
            return None, VerificationStatus.unverifiable
        trusted = f"{product.currency} {product.price:g}"
        return trusted, VerificationStatus.verified if abs(float(claimed) - product.price) < 0.5 else VerificationStatus.conflict
    key = {"warranty": "warranty_years", "capacity": "capacity", "power": "power_w", "weight": "weight_kg"}.get(attribute)
    trusted = product.attributes.get(key or "", "")
    if not trusted:
        return None, VerificationStatus.unverifiable
    t_num = re.findall(r"\d+(?:\.\d+)?", trusted)
    c_num = re.findall(r"\d+(?:\.\d+)?", claimed)
    if t_num and c_num:
        return trusted, VerificationStatus.verified if abs(float(t_num[0]) - float(c_num[0])) < 0.051 else VerificationStatus.conflict
    return trusted, VerificationStatus.inconclusive


def extract_claims(text: str, matcher: BrandMatcher, products: list[Product]) -> list[ProductClaim]:
    """Extract price / warranty / capacity / power claims tied to a brand in the same sentence."""
    claims: list[ProductClaim] = []
    target = matcher.workspace.brand.name
    brand_words = {w.lower() for w in re.split(r"\s+", target)} | {a.lower() for a in matcher.workspace.brand.aliases}
    # Brand-level warranty: the modal catalogue value, only if it covers >= 80% of products with a value
    warr_values = [p.attributes.get("warranty_years") for p in products if p.attributes.get("warranty_years")]
    brand_warranty = None
    if warr_values:
        mode, n = Counter(warr_values).most_common(1)[0]
        brand_warranty = Product(sku="_brand", name=target, attributes={"warranty_years": mode}) if n / len(warr_values) >= 0.8 else None
    for s in sentences(text):
        brands = matcher.brands_in(s)
        if target not in brands:
            continue  # only the target brand has trusted data to verify against
        # positions of every brand/product mention, used to attribute a value to the nearest preceding subject
        anchors: list[tuple[int, str]] = [(m.start(), b) for b in brands for m in matcher.patterns[b].finditer(s)]
        prods = _products_in_sentence(s, products, brand_words)
        for p in prods:
            for t in _product_tokens(p, brand_words)[:1]:
                for m in re.finditer(rf"\b{re.escape(t)}\b", s.lower()):
                    anchors.append((m.start(), target))
        anchors.sort()
        ambiguous = len(prods) > 1
        product = prods[0] if len(prods) == 1 else None
        for regex, attribute, fmt in (
            (PRICE_RE, "price", lambda m: m.group(1).replace(",", "")),
            (WARRANTY_RE, "warranty", lambda m: (m.group(1) or m.group(2)) + " years"),
            (CAPACITY_RE, "capacity", lambda m: m.group(1) + " L"),
            (POWER_RE, "power", lambda m: m.group(1) + " W"),
        ):
            for m in regex.finditer(s):
                if attribute == "price" and _is_bounded_price(s, m):
                    continue
                if len(brands) > 1:
                    before = [b for pos, b in anchors if pos < m.start()]
                    owner = before[-1] if before else anchors[0][1]
                    if owner != target:
                        continue
                claimed = fmt(m)
                if ambiguous:
                    status, trusted = VerificationStatus.unverifiable, None
                elif attribute == "warranty" and product is None:
                    trusted, status = _verify(attribute, claimed, brand_warranty)
                else:
                    trusted, status = _verify(attribute, claimed, product)
                claims.append(
                    ProductClaim(
                        brand=target,
                        product=product.name if product else (" / ".join(p.name for p in prods) if ambiguous else None),
                        attribute=attribute,
                        claimed_value=claimed if attribute != "price" else f"AED {claimed}",
                        quote=s,
                        trusted_value=trusted,
                        verification_status=status,
                        confidence=0.8 if product else 0.55,
                    )
                )
    # de-duplicate identical claims within a response
    uniq: dict[tuple, ProductClaim] = {}
    for c in claims:
        uniq.setdefault((c.attribute, c.claimed_value, c.product), c)
    return list(uniq.values())


# ---------------------------------------------------------------- extractors
def extract_naive(resp: RawResponse, workspace: Workspace, extraction_id: str) -> Extraction:
    """Baseline: substring match on canonical brand names only."""
    text_l = resp.text.lower()
    mentions = []
    order = sorted(
        ((text_l.find(b.lower()), b) for b in workspace.all_brands() if b.lower() in text_l),
    )
    for pos, (_, b) in enumerate(order, start=1):
        mentions.append(Mention(brand=b, is_target=b == workspace.brand.name, position=pos, evidence_quote=resp.text[:120], confidence=0.4))
    domains = [c.domain for c in resp.citations]
    return Extraction(
        id=extraction_id,
        response_id=resp.id,
        method="naive",
        mentions=mentions,
        cited_domains=sorted(set(domains)),
        target_mentioned=any(m.is_target for m in mentions),
        target_cited=workspace.brand.domain in domains,
        confidence=0.4,
        notes=["naive substring matcher; no sentiment or claims"],
    )


def extract_deterministic(resp: RawResponse, workspace: Workspace, products: list[Product], extraction_id: str) -> Extraction:
    matcher = BrandMatcher(workspace)
    text = resp.text or ""
    notes: list[str] = []
    if not resp.is_eligible:
        return Extraction(
            id=extraction_id, response_id=resp.id, method="deterministic", confidence=0.0,
            notes=[f"response status={resp.status.value}; excluded from metrics"],
        )
    found = matcher.find(text)
    sents = sentences(text)
    first_pos = sorted((ms[0].start(), b) for b, ms in found.items())
    mentions: list[Mention] = []
    for position, (start, brand) in enumerate(first_pos, start=1):
        brand_sents = [s for s in sents if matcher.patterns[brand].search(s)]
        sentiment, s_conf = classify_sentiment(brand_sents)
        mentions.append(
            Mention(
                brand=brand,
                is_target=brand == workspace.brand.name,
                position=position,
                list_rank=_list_rank(text, start),
                recommended=_is_recommended(brand_sents),
                sentiment=sentiment,
                evidence_quote=brand_sents[0] if brand_sents else text[max(0, start - 60): start + 80],
                attributes=detect_attributes(brand_sents),
                confidence=round(min(0.95, 0.75 + 0.05 * len(found[brand])) * (0.9 if sentiment == Sentiment.uncertain else 1.0), 2),
            )
        )
    citations = extract_citations(resp)
    domains = sorted({c.domain for c in citations if c.domain})
    target_cited = workspace.brand.domain in domains
    claims = extract_claims(text, matcher, products)
    target = next((m for m in mentions if m.is_target), None)
    if target and not brand_sents:
        notes.append("target matched but no sentence-level evidence found")
    if not citations:
        notes.append("no citations returned by provider")
    conf = 0.85 if mentions else 0.7
    if any(c.verification_status == VerificationStatus.conflict for c in claims):
        notes.append("contains claims conflicting with catalogue data")
    return Extraction(
        id=extraction_id,
        response_id=resp.id,
        method="deterministic",
        mentions=mentions,
        claims=claims,
        cited_domains=domains,
        target_mentioned=target is not None,
        target_cited=target_cited,
        target_sentiment=target.sentiment if target else Sentiment.uncertain,
        confidence=conf,
        notes=notes,
    )
