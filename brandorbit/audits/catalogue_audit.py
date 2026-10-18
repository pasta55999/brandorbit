"""Deterministic product-data audit.

Checks are intentionally rule-based so results are reproducible and explainable. Each issue
carries the SKU, the check name and a human-readable message. The framing throughout is
"hypothesis to test" - a missing attribute is a content gap, not a proven cause of poor visibility.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

from brandorbit.core.schemas import Product, Workspace

# Attributes that shoppers commonly ask about per category (used for "missing information" checks)
CATEGORY_EXPECTED: dict[str, list[str]] = {
    "air fryers": ["capacity", "power_w", "warranty_years"],
    "blenders": ["capacity", "power_w", "warranty_years", "noise_db"],
    "cordless vacuums": ["power_w", "warranty_years", "weight_kg", "noise_db"],
    "water purifiers": ["capacity", "warranty_years"],
    "coffee machines": ["capacity", "power_w", "warranty_years"],
    "kitchen essentials": ["capacity", "power_w", "warranty_years"],
}
UNIVERSAL_EXPECTED = ["price", "description", "url", "warranty_years"]
VAGUE_PHRASES = ["high quality", "best in class", "premium quality", "amazing", "perfect for everyone", "state of the art"]


@dataclass
class AuditIssue:
    sku: str
    check: str
    severity: Literal["high", "medium", "low"]
    message: str
    field_name: str = ""
    hypothesis: str = ""


@dataclass
class AuditResult:
    issues: list[AuditIssue] = field(default_factory=list)
    products_checked: int = 0
    attribute_coverage: dict[str, float] = field(default_factory=dict)

    def by_severity(self) -> dict[str, int]:
        out = {"high": 0, "medium": 0, "low": 0}
        for i in self.issues:
            out[i.severity] += 1
        return out

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([i.__dict__ for i in self.issues]) if self.issues else pd.DataFrame(columns=["sku", "check", "severity", "message", "field_name", "hypothesis"])


def _norm_name(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def audit_catalogue(products: list[Product], workspace: Optional[Workspace] = None, website_prices: Optional[dict[str, float]] = None) -> AuditResult:
    res = AuditResult(products_checked=len(products))
    if not products:
        return res
    all_attr_keys = sorted({k for p in products for k in p.attributes})
    coverage_hits = defaultdict(int)

    names_seen: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        names_seen[_norm_name(p.name)].append(p)
        for k in all_attr_keys:
            if p.attributes.get(k):
                coverage_hits[k] += 1
        # universal fields
        if p.price is None:
            res.issues.append(AuditIssue(p.sku, "missing_price", "high", "No price supplied", "price", "Answers cannot quote a price; price-bounded prompts may skip the product."))
        if not p.description or len(p.description) < 40:
            sev = "high" if not p.description else "medium"
            res.issues.append(AuditIssue(p.sku, "missing_description", sev, "Description missing" if not p.description else "Description is very short (<40 chars)", "description",
                                         "Thin descriptions give answer engines little to summarise or cite."))
        elif any(v in p.description.lower() for v in VAGUE_PHRASES):
            res.issues.append(AuditIssue(p.sku, "weak_differentiator", "low", "Description relies on unsupported superlatives", "description",
                                         "Unsupported claims are rarely repeated by answer engines; concrete specs are."))
        if not p.url:
            res.issues.append(AuditIssue(p.sku, "missing_url", "medium", "No product URL supplied", "url", "Without a canonical URL the product page cannot be cited."))
        elif workspace and workspace.brand.domain and workspace.brand.domain not in p.url:
            res.issues.append(AuditIssue(p.sku, "url_domain_mismatch", "low", f"Product URL is not on {workspace.brand.domain}", "url"))
        # category-expected attributes
        expected = CATEGORY_EXPECTED.get(p.category.lower(), ["warranty_years"])
        for attr in expected:
            if not p.attributes.get(attr):
                res.issues.append(AuditIssue(p.sku, "missing_attribute", "medium" if attr != "noise_db" else "low", f"Missing '{attr}' (commonly asked for {p.category})", attr,
                                             f"Prompts that ask about {attr.replace('_', ' ')} cannot be answered from this record."))
        # spec/description consistency: capacity in name vs attribute
        m = re.search(r"(\d+(?:\.\d+)?)\s?L\b", p.name)
        cap = p.attributes.get("capacity", "")
        if m and cap and abs(float(m.group(1)) - float(re.findall(r"\d+(?:\.\d+)?", cap)[0])) > 0.05:
            res.issues.append(AuditIssue(p.sku, "inconsistent_spec", "medium", f"Capacity in name ({m.group(1)} L) differs from attribute ({cap})", "capacity"))
        if website_prices and p.sku in website_prices and p.price is not None and abs(website_prices[p.sku] - p.price) > 0.5:
            res.issues.append(AuditIssue(p.sku, "price_mismatch", "high", f"Catalogue price {p.currency} {p.price:g} differs from website price {p.currency} {website_prices[p.sku]:g}", "price",
                                         "Conflicting prices across sources make it likely that answers will quote the wrong one."))

    # duplicate / inconsistent names
    for norm, group in names_seen.items():
        if len(group) > 1:
            prices = {p.price for p in group}
            warr = {p.attributes.get("warranty_years") for p in group}
            detail = []
            if len(prices) > 1:
                detail.append(f"prices {sorted(x for x in prices if x is not None)}")
            if len(warr) > 1:
                detail.append(f"warranty {sorted(str(w) for w in warr)}")
            for p in group:
                res.issues.append(AuditIssue(p.sku, "inconsistent_naming", "medium", f"Same product name used by {len(group)} SKUs with differing {', '.join(detail) or 'details'}", "name",
                                             "Ambiguous naming can lead to merged or contradictory product facts in answers."))
    # casing inconsistencies in model names (e.g. BrewMaster vs Brewmaster)
    tokens: dict[str, set[str]] = defaultdict(set)
    for p in products:
        for t in re.findall(r"[A-Za-z]{6,}", p.name):
            tokens[t.lower()].add(t)
    for low, variants in tokens.items():
        if len(variants) > 1:
            for p in products:
                if any(v in p.name for v in variants):
                    res.issues.append(AuditIssue(p.sku, "inconsistent_naming", "low", f"Model name casing varies across catalogue: {', '.join(sorted(variants))}", "name"))
    res.attribute_coverage = {k: round(100 * coverage_hits[k] / len(products), 1) for k in all_attr_keys}
    # de-duplicate
    seen = set()
    uniq = []
    for i in res.issues:
        key = (i.sku, i.check, i.message)
        if key not in seen:
            seen.add(key)
            uniq.append(i)
    res.issues = uniq
    return res
