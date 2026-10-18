"""Evaluation harness for the extraction pipeline.

Usage:
    python -m evaluation.run_eval            # deterministic + naive methods
    python -m evaluation.run_eval --llm      # also run LLM-assisted extraction if a live provider is configured

Reports precision/recall for brand-mention detection, accuracy of target sentiment, website citation detection,
and claim verification outcomes against data/eval/labelled_responses.json. Nothing here is invented: numbers are
computed from the labelled cases at run time.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from brandorbit.analysis.extraction import extract_deterministic, extract_naive
from brandorbit.analysis.llm import llm_extract
from brandorbit.core.catalogue import parse_catalogue_csv
from brandorbit.core.schemas import Citation, Extraction, RawResponse, ResponseStatus
from brandorbit.monitoring.demo_loader import DEMO_DIR, demo_workspace
from brandorbit.providers import first_live_provider

EVAL_PATH = Path(__file__).resolve().parents[1] / "data" / "eval" / "labelled_responses.json"


@dataclass
class Scores:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    sentiment_correct: int = 0
    sentiment_total: int = 0
    cited_correct: int = 0
    cited_total: int = 0
    claim_status_correct: int = 0
    claim_status_total: int = 0
    claim_missing: int = 0
    claim_extra: int = 0
    rank_correct: int = 0
    rank_total: int = 0
    recommend_correct: int = 0
    recommend_total: int = 0
    ineligible_handled: int = 0
    ineligible_total: int = 0
    failures: list[str] = field(default_factory=list)
    confusion: Counter = field(default_factory=Counter)

    def prf(self) -> tuple[float, float, float]:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        return round(p, 3), round(r, 3), round(f, 3)


def load_cases() -> list[dict]:
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))["cases"]


def to_response(case: dict) -> RawResponse:
    return RawResponse(id=case["id"], run_id="eval", prompt_id="eval", provider="eval", model="eval", text=case.get("text", ""),
                       citations=[Citation(**c) for c in case.get("citations", [])], status=ResponseStatus(case.get("status", "ok")), error=case.get("error"))


def score(case: dict, ext: Extraction, s: Scores) -> None:
    exp = case["expect"]
    got = {m.brand for m in ext.mentions}
    want = set(exp["brands"])
    s.tp += len(got & want)
    s.fp += len(got - want)
    s.fn += len(want - got)
    if got != want:
        s.failures.append(f"{case['id']} [{case['tag']}] brands: expected {sorted(want)}, got {sorted(got)}")
    if exp.get("eligible") is False:
        s.ineligible_total += 1
        if not ext.mentions and ext.confidence == 0.0:
            s.ineligible_handled += 1
        return
    if exp["target_sentiment"] is not None and ext.target_mentioned:
        s.sentiment_total += 1
        s.confusion[(exp["target_sentiment"], ext.target_sentiment.value)] += 1
        if ext.target_sentiment.value == exp["target_sentiment"]:
            s.sentiment_correct += 1
        else:
            s.failures.append(f"{case['id']} [{case['tag']}] sentiment: expected {exp['target_sentiment']}, got {ext.target_sentiment.value}")
    s.cited_total += 1
    if ext.target_cited == exp["target_cited"]:
        s.cited_correct += 1
    else:
        s.failures.append(f"{case['id']} [{case['tag']}] target_cited: expected {exp['target_cited']}, got {ext.target_cited}")
    if "cited_domains" in exp and set(ext.cited_domains) != set(exp["cited_domains"]):
        s.failures.append(f"{case['id']} cited_domains: expected {exp['cited_domains']}, got {ext.cited_domains}")
    # claims: compare by attribute -> status
    want_claims = Counter((c["attribute"], c["status"]) for c in exp["claims"])
    got_claims = Counter((c.attribute, c.verification_status.value) for c in ext.claims)
    s.claim_status_total += sum(want_claims.values())
    s.claim_status_correct += sum((want_claims & got_claims).values())
    s.claim_missing += sum((want_claims - got_claims).values())
    s.claim_extra += sum((got_claims - want_claims).values())
    if want_claims != got_claims:
        s.failures.append(f"{case['id']} [{case['tag']}] claims: expected {dict(want_claims)}, got {dict(got_claims)}")
    if "target_list_rank" in exp:
        s.rank_total += 1
        t = next((m for m in ext.mentions if m.is_target), None)
        s.rank_correct += int(bool(t and t.list_rank == exp["target_list_rank"]))
    for b in exp.get("recommended", []):
        s.recommend_total += 1
        s.recommend_correct += int(any(m.brand == b and m.recommended for m in ext.mentions))
    for b in exp.get("not_recommended", []):
        s.recommend_total += 1
        s.recommend_correct += int(any(m.brand == b and not m.recommended for m in ext.mentions))


def run(method: str, cases: list[dict]) -> Scores | None:
    ws = demo_workspace()
    products = parse_catalogue_csv((DEMO_DIR / "catalogue.csv").read_bytes())
    s = Scores()
    provider = first_live_provider() if method == "llm" else None
    if method == "llm" and provider is None:
        return None
    for case in cases:
        resp = to_response(case)
        if method == "naive":
            ext = extract_naive(resp, ws, f"ext_{case['id']}")
        elif method == "deterministic":
            ext = extract_deterministic(resp, ws, products, f"ext_{case['id']}")
        else:
            ext = llm_extract(resp, ws, provider, f"ext_{case['id']}") or Extraction(id="x", response_id=resp.id, method="llm", confidence=0.0)
        score(case, ext, s)
    return s


def render(method: str, s: Scores | None, n: int) -> str:
    if s is None:
        return f"### Method: {method}\n\nNot run - no live provider configured (set OPENAI_API_KEY or ANTHROPIC_API_KEY).\n"
    p, r, f = s.prf()
    lines = [f"### Method: {method}", "", f"Cases: {n}", "", "| Metric | Value | n |", "|---|---|---|",
             f"| Brand-mention precision | {p:.3f} | tp={s.tp}, fp={s.fp} |",
             f"| Brand-mention recall | {r:.3f} | tp={s.tp}, fn={s.fn} |",
             f"| Brand-mention F1 | {f:.3f} | |",
             f"| Target sentiment accuracy | {s.sentiment_correct}/{s.sentiment_total} | {('%.3f' % (s.sentiment_correct / s.sentiment_total)) if s.sentiment_total else 'n/a'} |",
             f"| Website-citation detection accuracy | {s.cited_correct}/{s.cited_total} | {('%.3f' % (s.cited_correct / s.cited_total)) if s.cited_total else 'n/a'} |",
             f"| Claim (attribute, verification status) recall | {s.claim_status_correct}/{s.claim_status_total} | missing={s.claim_missing}, extra={s.claim_extra} |",
             f"| List-rank detection | {s.rank_correct}/{s.rank_total} | |",
             f"| Recommendation flag | {s.recommend_correct}/{s.recommend_total} | |",
             f"| Ineligible responses excluded | {s.ineligible_handled}/{s.ineligible_total} | |", ""]
    if s.confusion:
        lines += ["Sentiment confusion (expected -> got): " + ", ".join(f"{a}->{b}: {n}" for (a, b), n in sorted(s.confusion.items())), ""]
    lines += ["Failure cases:", ""] + ([f"- {x}" for x in s.failures] or ["- none"]) + [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="Write the markdown report to this path")
    args = ap.parse_args()
    cases = load_cases()
    methods = ["naive", "deterministic"] + (["llm"] if args.llm else [])
    report = ["## Extraction evaluation results", "", f"Source: `{EVAL_PATH.relative_to(EVAL_PATH.parents[2])}` ({len(cases)} labelled cases).", ""]
    for m in methods:
        report.append(render(m, run(m, cases), len(cases)))
    text = "\n".join(report)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
