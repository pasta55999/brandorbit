from __future__ import annotations

import json

import pytest

from brandorbit.analysis.extraction import extract_citations, extract_deterministic, extract_naive
from brandorbit.core.schemas import Citation, RawResponse, ResponseStatus, Sentiment, VerificationStatus
from evaluation.run_eval import EVAL_PATH, run as run_eval


def resp(text: str, citations: list[str] | None = None, status: str = "ok") -> RawResponse:
    return RawResponse(id="r1", run_id="run", prompt_id="p", provider="t", model="t", text=text,
                       citations=[Citation(url=u) for u in (citations or [])], status=ResponseStatus(status))


def test_alias_and_domain_matching(ws, products):
    e = extract_deterministic(resp("Seraj ships fast; see serajhome.ae and homenest.ae."), ws, products, "e")
    assert {m.brand for m in e.mentions} == {"Seraj Home", "HomeNest UAE"}
    assert e.target_mentioned


def test_word_boundary_prevents_substring_false_positive(ws, products):
    e = extract_deterministic(resp("The Falconer's Guide lists KitchenKart."), ws, products, "e")
    assert {m.brand for m in e.mentions} == {"KitchenKart"}


def test_position_and_list_rank(ws, products):
    e = extract_deterministic(resp("Top picks:\n\n1. HomeNest UAE 6L\n2. Seraj Home AirCrisp\n3. KitchenKart Basic"), ws, products, "e")
    t = next(m for m in e.mentions if m.is_target)
    assert t.position == 2 and t.list_rank == 2


def test_sentiment_labels(ws, products):
    pos = extract_deterministic(resp("Seraj Home is a reliable choice with excellent support."), ws, products, "e")
    neg = extract_deterministic(resp("Seraj Home's vacuum has poor battery life and many complaints."), ws, products, "e")
    unc = extract_deterministic(resp("Some users report Seraj Home blenders are quieter, although reviews are mixed."), ws, products, "e")
    neu = extract_deterministic(resp("Seraj Home sells blenders and kettles online."), ws, products, "e")
    assert pos.target_sentiment == Sentiment.positive
    assert neg.target_sentiment == Sentiment.negative
    assert unc.target_sentiment == Sentiment.uncertain
    assert neu.target_sentiment == Sentiment.neutral


def test_negated_recommendation_not_flagged(ws, products):
    e = extract_deterministic(resp("I would not recommend Seraj Home for heavy blending."), ws, products, "e")
    assert not next(m for m in e.mentions if m.is_target).recommended


def test_price_claim_conflict_and_verified(ws, products):
    bad = extract_deterministic(resp("The Seraj AirCrisp 5.5L costs AED 349."), ws, products, "e")
    good = extract_deterministic(resp("The Seraj AirCrisp 5.5L costs AED 299."), ws, products, "e")
    assert any(c.attribute == "price" and c.verification_status == VerificationStatus.conflict and c.trusted_value == "AED 299" for c in bad.claims)
    assert any(c.attribute == "price" and c.verification_status == VerificationStatus.verified for c in good.claims)


def test_budget_bound_is_not_a_price_claim(ws, products):
    e = extract_deterministic(resp("Under AED 400, Seraj Home's VitaBlend Pro at AED 349 is a good fit."), ws, products, "e")
    prices = [c.claimed_value for c in e.claims if c.attribute == "price"]
    assert prices == ["AED 349"]


def test_multi_brand_sentence_attributes_price_to_nearest_subject(ws, products):
    e = extract_deterministic(resp("HomeNest UAE's 6L model is AED 259, while Seraj Home's AirCrisp 5.5L is AED 299."), ws, products, "e")
    prices = [(c.claimed_value, c.verification_status) for c in e.claims if c.attribute == "price"]
    assert prices == [("AED 299", VerificationStatus.verified)]


def test_unknown_product_is_unverifiable(ws, products):
    e = extract_deterministic(resp("Seraj Home's new toaster is AED 129."), ws, products, "e")
    assert e.claims and all(c.verification_status == VerificationStatus.unverifiable for c in e.claims)


def test_brand_level_warranty_uses_modal_catalogue_value(ws, products):
    e = extract_deterministic(resp("Seraj Home offers a 1-year warranty on most items."), ws, products, "e")
    w = next(c for c in e.claims if c.attribute == "warranty")
    assert w.verification_status == VerificationStatus.conflict and w.trusted_value == "2"


def test_citations_include_inline_urls(ws, products):
    r = resp("See https://www.serajhome.ae/pages/warranty for details.", ["https://uaehomeguide.com/x"])
    assert {c.domain for c in extract_citations(r)} == {"serajhome.ae", "uaehomeguide.com"}
    e = extract_deterministic(r, ws, products, "e")
    assert e.target_cited and e.cited_domains == ["serajhome.ae", "uaehomeguide.com"]


@pytest.mark.parametrize("status", ["error", "timeout", "malformed"])
def test_ineligible_response_yields_empty_extraction(ws, products, status):
    e = extract_deterministic(resp("", status=status), ws, products, "e")
    assert e.mentions == [] and e.confidence == 0.0 and "excluded" in e.notes[0]


def test_naive_misses_alias(ws):
    e = extract_naive(resp("Seraj ships across the UAE."), ws, "e")
    assert not e.target_mentioned


def test_evidence_quotes_are_verbatim(ws, products):
    text = "HomeNest UAE is popular. Seraj Home's AirCrisp 5.5L is well reviewed and costs AED 299."
    e = extract_deterministic(resp(text), ws, products, "e")
    for m in e.mentions:
        assert m.evidence_quote in text
    for c in e.claims:
        assert c.quote in text


def test_evaluation_thresholds():
    """Guards against regressions on the labelled set; thresholds are below current results on purpose."""
    cases = json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]
    det = run_eval("deterministic", cases)
    naive = run_eval("naive", cases)
    p, r, f = det.prf()
    assert r == 1.0 and p >= 0.95
    assert det.sentiment_correct / det.sentiment_total >= 0.75
    assert det.cited_correct == det.cited_total
    assert det.claim_missing == 0
    assert det.ineligible_handled == det.ineligible_total
    assert naive.prf()[1] < r  # the rule-based extractor must beat the naive baseline on recall
