from __future__ import annotations

import json

import pytest

from brandorbit.analysis.llm import llm_extract, suggest_prompts, template_prompts
from brandorbit.analysis.recommendations import narrate
from brandorbit.audits.catalogue_audit import audit_catalogue
from brandorbit.audits.website_audit import inspect_html, load_snapshot
from brandorbit.core.catalogue import CatalogueError, parse_catalogue_csv
from brandorbit.core.schemas import Citation, Evidence, Finding, RawResponse, SourceKind
from brandorbit.monitoring.demo_loader import DEMO_DIR
from brandorbit.providers.base import Provider, ProviderResult


# ------------------------------------------------------------------ catalogue
def test_catalogue_parse_and_validation():
    prods = parse_catalogue_csv(b"sku,name,price,power_w\nA1,Widget,10,100\n")
    assert prods[0].attributes == {"power_w": "100"} and prods[0].price == 10.0
    with pytest.raises(CatalogueError):
        parse_catalogue_csv(b"name\nx\n")  # missing sku
    with pytest.raises(CatalogueError):
        parse_catalogue_csv(b"sku,name\nA,x\nA,y\n")  # duplicate sku
    with pytest.raises(CatalogueError):
        parse_catalogue_csv(b"x" * 10, max_bytes=5)  # too large


def test_catalogue_audit_detects_seeded_issues(products, ws):
    res = audit_catalogue(products, ws, website_prices={"SH-AF-80": 499.0, "SH-WP-10": 949.0})
    checks = {(i.sku, i.check) for i in res.issues}
    assert ("SH-BL-06", "missing_description") in checks
    assert ("SH-BL-06", "missing_attribute") in checks  # power_w missing
    assert ("SH-KT-40", "inconsistent_naming") in checks and ("SH-KT-41", "inconsistent_naming") in checks
    assert ("SH-AF-80", "price_mismatch") in checks and ("SH-WP-10", "price_mismatch") in checks
    assert ("SH-CM-30", "inconsistent_naming") in checks  # BrewMaster vs Brewmaster casing
    assert all(i.hypothesis == "" or "visib" in i.hypothesis or "answer" in i.hypothesis.lower() or "cite" in i.hypothesis.lower() or "price" in i.hypothesis.lower() for i in res.issues)


def test_website_snapshot_and_html_inspection():
    web = load_snapshot((DEMO_DIR / "website_snapshot.csv").read_bytes())
    issues = {(i["sku"], i["check"]) for i in web.issues()}
    assert ("SH-BL-06", "missing_structured_data") in issues and ("SH-AF-80", "structured_data_without_price") in issues
    html = """<html><head><title>Widget | Shop</title><meta name="description" content="A very useful widget for every kitchen in the UAE.">
    <script type="application/ld+json">{"@type": "Product", "name": "Widget", "offers": {"@type": "Offer", "price": "299.00"}}</script></head><body></body></html>"""
    pc = inspect_html("W1", "https://example.ae/w", html)
    assert pc.has_product_schema and pc.has_price_in_schema and pc.listed_price == 299.0 and pc.has_description and pc.title.startswith("Widget")
    bad = inspect_html("W2", "https://example.ae/x", "<html><head><title>x</title></head></html>")
    assert bad.has_product_schema is False and bad.has_description is False


# ------------------------------------------------------------------------ llm
class FakeLLM(Provider):
    id = "fake"
    model = "fake-1"
    source_kind = SourceKind.live

    def __init__(self, payload):
        self.payload = payload

    def answer(self, *a, **k):
        return ProviderResult(text="")

    def structured(self, system, user, schema_name):
        return self.payload


def test_llm_extraction_drops_non_verbatim_quotes_and_unknown_brands(ws):
    resp = RawResponse(id="r", run_id="x", prompt_id="p", provider="t", model="m", text="Seraj Home is a reliable option in Dubai.", citations=[Citation(url="https://www.serajhome.ae/")])
    payload = json.dumps({
        "mentions": [
            {"brand": "Seraj Home", "is_target": True, "position": 1, "sentiment": "positive", "evidence_quote": "Seraj Home is a reliable option in Dubai.", "confidence": 0.9},
            {"brand": "HomeNest UAE", "is_target": False, "position": 2, "sentiment": "neutral", "evidence_quote": "HomeNest UAE is cheaper.", "confidence": 0.9},
            {"brand": "Acme", "is_target": False, "position": 3, "sentiment": "neutral", "evidence_quote": "Seraj Home is a reliable option in Dubai.", "confidence": 0.9},
        ],
        "claims": [{"brand": "Seraj Home", "attribute": "price", "claimed_value": "AED 99", "quote": "costs AED 99", "confidence": 0.8}],
        "overall_confidence": 0.8,
    })
    e = llm_extract(resp, ws, FakeLLM(payload), "e")
    assert [m.brand for m in e.mentions] == ["Seraj Home"]
    assert e.claims == [] and e.target_cited and e.method == "llm"
    assert any("quote not found" in n for n in e.notes) and any("unknown brand" in n for n in e.notes)


def test_llm_extraction_handles_malformed_output(ws):
    resp = RawResponse(id="r", run_id="x", prompt_id="p", provider="t", model="m", text="Seraj Home is fine.")
    e = llm_extract(resp, ws, FakeLLM("{not json"), "e")
    assert e.confidence == 0.0 and "schema validation failed" in e.notes[0]
    assert llm_extract(resp, ws, FakeLLM(None), "e") is None


def test_narrator_cannot_introduce_new_quotes():
    f = Finding(id="x", workspace_id="w", run_id="r", finding_id="F-GAP-001", category="visibility_gap", severity="high", title="t", explanation="orig",
                proposed_action="a", expected_outcome="h", confidence=0.8, evidence=[Evidence(prompt_id="p", response_id="r", quote="real quote")])
    ok = json.dumps({"finding_id": "F-GAP-001", "explanation": "new", "proposed_action": "do", "expected_outcome": "maybe", "confidence": 0.6, "quotes_used": ["real quote"]})
    bad = json.dumps({"finding_id": "F-GAP-001", "explanation": "new", "proposed_action": "do", "expected_outcome": "maybe", "confidence": 0.6, "quotes_used": ["invented quote"]})
    assert narrate(f, FakeLLM(ok)).explanation == "new" and narrate(f, FakeLLM(ok)).confidence == 0.6
    assert narrate(f, FakeLLM(bad)).explanation == "orig"
    assert narrate(f, FakeLLM("garbage")).generated_by == "rules"


def test_prompt_suggestions_fall_back_to_templates(ws, products):
    sugg, source = suggest_prompts(ws, products, None)
    assert "Template" in source and len(sugg) >= 10
    assert {s.category.value for s in sugg} == {"discovery", "comparison", "product_specific", "problem_solving", "purchase_intent"}
    assert all("AED" in s.text for s in sugg if s.category.value == "product_specific")
    assert sugg == template_prompts(ws, products)
