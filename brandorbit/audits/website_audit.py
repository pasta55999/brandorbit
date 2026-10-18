"""Website inspection.

Two sources are supported:

* A *snapshot CSV* (demo mode) describing what a crawl found per product page. The demo
  snapshot is fictional and labelled as such.
* *Live inspection* of a handful of public product pages with a small HTTP client. This is
  opt-in (``BRANDORBIT_ALLOW_WEBSITE_FETCH=true``), respects ``robots.txt`` disallow rules for
  the fetched paths, fetches at most ``max_pages`` pages, and only looks for JSON-LD Product
  structured data, a price and a description. Fetched HTML is treated as untrusted data and
  never executed or fed to a model as instructions.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
import pandas as pd

from brandorbit.core.schemas import Product

log = logging.getLogger(__name__)
USER_AGENT = "BrandOrbit-audit/0.1 (+portfolio prototype; respects robots.txt)"


@dataclass
class PageCheck:
    sku: str
    url: str
    fetched: bool
    has_product_schema: Optional[bool] = None
    has_price_in_schema: Optional[bool] = None
    has_description: Optional[bool] = None
    listed_price: Optional[float] = None
    title: str = ""
    note: str = ""
    source: str = "snapshot"


@dataclass
class WebsiteAudit:
    checks: list[PageCheck] = field(default_factory=list)
    source: str = "snapshot"

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([c.__dict__ for c in self.checks])

    def price_map(self) -> dict[str, float]:
        return {c.sku: c.listed_price for c in self.checks if c.listed_price is not None}

    def issues(self) -> list[dict]:
        out = []
        for c in self.checks:
            if not c.fetched:
                out.append({"sku": c.sku, "check": "page_not_inspected", "severity": "low", "message": c.note or "Page not inspected"})
                continue
            if c.has_product_schema is False:
                out.append({"sku": c.sku, "check": "missing_structured_data", "severity": "medium", "message": "No schema.org Product JSON-LD found on page"})
            elif c.has_price_in_schema is False:
                out.append({"sku": c.sku, "check": "structured_data_without_price", "severity": "low", "message": "Product JSON-LD present but no offers/price"})
            if c.has_description is False:
                out.append({"sku": c.sku, "check": "missing_page_description", "severity": "medium", "message": "No meaningful description detected on page"})
        return out


def load_snapshot(csv_bytes: bytes) -> WebsiteAudit:
    df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False)
    audit = WebsiteAudit(source="snapshot (demo fixture)")
    for _, r in df.iterrows():
        audit.checks.append(PageCheck(
            sku=r["sku"], url=r["page_url"], fetched=True,
            has_product_schema=r.get("has_product_schema", "").lower() == "true",
            has_price_in_schema=r.get("has_price_in_schema", "").lower() == "true",
            has_description=r.get("has_description", "").lower() == "true",
            listed_price=float(r["listed_price"]) if r.get("listed_price") else None,
            title=r.get("title_tag", ""), note=r.get("snapshot_note", ""), source="snapshot",
        ))
    return audit


# ------------------------------------------------------------------ live mode
def _robots_allows(client: httpx.Client, url: str, cache: dict[str, RobotFileParser]) -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in cache:
        rp = RobotFileParser()
        try:
            r = client.get(base + "/robots.txt")
            rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        except httpx.HTTPError:
            rp.parse([])
        cache[base] = rp
    return cache[base].can_fetch(USER_AGENT, url)


def inspect_live(products: list[Product], max_pages: int = 5, timeout_s: float = 10.0) -> WebsiteAudit:
    audit = WebsiteAudit(source="live fetch")
    robots: dict[str, RobotFileParser] = {}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout_s, follow_redirects=True) as client:
        for p in [x for x in products if x.url][:max_pages]:
            if not _robots_allows(client, p.url, robots):
                audit.checks.append(PageCheck(p.sku, p.url, fetched=False, note="Disallowed by robots.txt", source="live"))
                continue
            try:
                r = client.get(p.url)
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    audit.checks.append(PageCheck(p.sku, p.url, fetched=False, note=f"HTTP {r.status_code}", source="live"))
                    continue
                audit.checks.append(inspect_html(p.sku, p.url, r.text[:1_000_000]))
            except httpx.HTTPError as exc:
                audit.checks.append(PageCheck(p.sku, p.url, fetched=False, note=f"{type(exc).__name__}", source="live"))
    return audit


_JSONLD = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC = re.compile(r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']{20,})", re.I)


def inspect_html(sku: str, url: str, html: str) -> PageCheck:
    """Pure function over HTML text (also used in tests)."""
    has_schema = has_price = False
    price = None
    for block in _JSONLD.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and "Product" in str(node.get("@type", "")):
                has_schema = True
                offers = node.get("offers") or {}
                offers = offers[0] if isinstance(offers, list) and offers else offers
                if isinstance(offers, dict) and offers.get("price"):
                    has_price = True
                    try:
                        price = float(str(offers["price"]).replace(",", ""))
                    except ValueError:
                        pass
    title = re.sub(r"\s+", " ", (_TITLE.search(html) or [None, ""])[1]).strip() if _TITLE.search(html) else ""
    desc = bool(_META_DESC.search(html))
    return PageCheck(sku, url, fetched=True, has_product_schema=has_schema, has_price_in_schema=has_price if has_schema else None,
                     has_description=desc, listed_price=price, title=title[:120], source="live")
