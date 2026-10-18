"""Product catalogue CSV parsing and validation (user uploads and demo data)."""

from __future__ import annotations

import io
from typing import Optional

import pandas as pd

from brandorbit.core.schemas import Product

REQUIRED_COLUMNS = {"sku", "name"}
KNOWN_COLUMNS = {"sku", "name", "category", "price", "currency", "description", "url"}
MAX_ROWS = 2000


class CatalogueError(ValueError):
    pass


def parse_catalogue_csv(content: bytes | str, default_currency: str = "AED", max_bytes: int = 2 * 1024 * 1024) -> list[Product]:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if len(raw) > max_bytes:
        raise CatalogueError(f"Catalogue file is too large ({len(raw)/1024:.0f} KB > {max_bytes/1024:.0f} KB)")
    try:
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception as exc:  # pandas raises many parser error types
        raise CatalogueError(f"Could not parse CSV: {exc}") from exc
    df.columns = [c.strip().lower() for c in df.columns]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise CatalogueError(f"CSV is missing required columns: {', '.join(sorted(missing))}")
    if len(df) > MAX_ROWS:
        raise CatalogueError(f"Catalogue has {len(df)} rows; the limit is {MAX_ROWS}")
    products: list[Product] = []
    seen: set[str] = set()
    for i, row in df.iterrows():
        sku = row["sku"].strip()
        if not sku:
            raise CatalogueError(f"Row {i + 2}: sku is empty")
        if sku in seen:
            raise CatalogueError(f"Duplicate sku {sku!r} at row {i + 2}")
        seen.add(sku)
        price = _to_float(row.get("price", ""))
        attrs = {k: str(v).strip() for k, v in row.items() if k not in KNOWN_COLUMNS and str(v).strip()}
        products.append(
            Product(
                sku=sku,
                name=row["name"].strip(),
                category=row.get("category", "").strip(),
                price=price,
                currency=(row.get("currency", "") or default_currency).strip() or default_currency,
                description=row.get("description", "").strip(),
                url=row.get("url", "").strip(),
                attributes=attrs,
            )
        )
    return products


def _to_float(v: str) -> Optional[float]:
    v = (v or "").replace(",", "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def products_to_frame(products: list[Product]) -> pd.DataFrame:
    rows = []
    for p in products:
        rows.append({"sku": p.sku, "name": p.name, "category": p.category, "price": p.price, "currency": p.currency,
                     "description": p.description, "url": p.url, **p.attributes})
    return pd.DataFrame(rows)
