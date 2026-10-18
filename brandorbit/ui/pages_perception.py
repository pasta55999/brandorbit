from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import join_records
from brandorbit.core.schemas import Sentiment, VerificationStatus
from brandorbit.ui.common import bar_chart, coverage_caption, demo_banner, get_repo, page_header, quote, run_metrics, select_run, select_workspace, short_pid

STRENGTH_SENT = {Sentiment.positive}
WEAK_SENT = {Sentiment.negative, Sentiment.uncertain}


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = select_run(repo, ws)
    page_header("Brand perception", "How answers describe the brand: sentiment, associated attributes, and claims checked against the catalogue.")
    demo_banner(ws, run)
    if run is None:
        st.info("No runs yet.")
        return
    m = run_metrics(repo, ws, run)
    coverage_caption(m)
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    target_mentions = [(r, x) for r in records for x in r.extraction.mentions if x.is_target]

    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown("#### Sentiment of brand mentions")
        total = sum(m.sentiment_counts.values()) or 1
        df = pd.DataFrame([{"sentiment": k, "share": round(100 * v / total, 1), "count": v} for k, v in m.sentiment_counts.items()])
        bar_chart(df, "sentiment", "share", height=200)
        st.caption(f"n = {total} brand mentions. Lexicon-based classification; hedged or mixed statements are labelled 'uncertain' rather than guessed.")
    with c2:
        st.markdown("#### Attributes associated with the brand")
        attrs = Counter(a for _, x in target_mentions for a in x.attributes)
        if attrs:
            df = pd.DataFrame([{"attribute": a, "mentions": n} for a, n in attrs.most_common(12)])
            bar_chart(df, "attribute", "mentions", pct=False, height=260)
        else:
            st.info("No attribute cues detected in brand sentences.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("#### Frequently mentioned strengths")
        for r, x in [(r, x) for r, x in target_mentions if x.sentiment in STRENGTH_SENT][:6]:
            quote(x.evidence_quote)
            st.caption(f"{short_pid(r.prompt.id)} - {r.response.provider} - attributes: {', '.join(x.attributes) or '-'}")
    with c4:
        st.markdown("#### Weaknesses and hedged descriptions")
        weak = [(r, x) for r, x in target_mentions if x.sentiment in WEAK_SENT]
        if not weak:
            st.success("No negative or uncertain brand descriptions in this run.")
        for r, x in weak[:6]:
            quote(x.evidence_quote)
            st.caption(f"{short_pid(r.prompt.id)} - {r.response.provider} - {x.sentiment.value} (confidence {x.confidence:.0%})")

    st.markdown("#### Product claims and verification status")
    rows = []
    for r in records:
        for c in r.extraction.claims:
            rows.append({"status": c.verification_status.value, "attribute": c.attribute, "product": c.product or "(brand-level)", "claimed": c.claimed_value,
                         "trusted (catalogue)": c.trusted_value or "-", "prompt": short_pid(r.prompt.id), "provider": r.response.provider, "quote": c.quote, "response_id": r.response.id})
    if rows:
        df = pd.DataFrame(rows)
        order = {"conflict": 0, "unverifiable": 1, "inconclusive": 2, "verified": 3}
        df = df.sort_values("status", key=lambda s: s.map(order))
        f = st.multiselect("Filter status", list(order), default=list(order))
        st.dataframe(df[df["status"].isin(f)], use_container_width=True, hide_index=True)
        n_conf = sum(1 for x in rows if x["status"] == "conflict")
        st.caption(f"{len(rows)} claims extracted: {n_conf} conflict with the catalogue, {m.unverifiable_claims} could not be verified. "
                   "Verification compares against user-supplied data, which may itself be outdated. Claims spanning multiple sentences are not captured.")
    else:
        st.info("No product claims detected in this run.")
