from __future__ import annotations

from collections import Counter

import pandas as pd
import streamlit as st

from brandorbit.core.metrics import join_records
from brandorbit.core.schemas import Sentiment, VerificationStatus
from brandorbit.ui.common import (
    chip, coverage_line, df_table, empty_state, get_repo, guard_run, hbar, page_header, quote, raw_block, run_metrics, section, sentiment_bar, select_workspace, short_pid, source_tag,
)


def render() -> None:
    repo = get_repo()
    ws = select_workspace(repo)
    run = page_header("Brand Perception", "How answers describe the brand, and where they get the facts wrong.", repo=repo, ws=ws, with_run=True)
    if not guard_run(repo, ws, run):
        return
    m = run_metrics(repo, ws, run)
    prompts = repo.list_prompts(ws.id)
    records, _ = join_records(prompts, repo.list_responses(run.id), repo.list_extractions(run.id))
    mentions = [(r, x) for r in records for x in r.extraction.mentions if x.is_target]
    coverage_line(m)

    left, right = st.columns([3, 2])
    with left:
        section("Sentiment of brand mentions", f"{len(mentions)} mentions")
        sentiment_bar(m.sentiment_counts)
        st.caption("English lexicon classification. Hedged or mixed statements are labelled uncertain rather than guessed." + (" Small sample - treat shares as indicative." if len(mentions) < 20 else ""))
    with right:
        section("Themes", "attributes attached to the brand")
        attrs = Counter(a for _, x in mentions for a in x.attributes)
        if attrs:
            st.markdown(" ".join(chip(f"{a} - {n}", "neutral") for a, n in attrs.most_common(10)), unsafe_allow_html=True)
        else:
            empty_state("No attribute cues detected")

    conflicts = [(r, c) for r in records for c in r.extraction.claims if c.verification_status == VerificationStatus.conflict]
    section("Potential factual inaccuracies", f"{len(conflicts)} conflicting claims")
    if not conflicts:
        st.markdown(chip("No conflicts with the catalogue in this run", "good"), unsafe_allow_html=True)
    for r, c in conflicts:
        with st.expander(f"{c.attribute.title()} - {c.product or ws.brand.name}: answer says {c.claimed_value}, catalogue says {c.trusted_value}"):
            quote(c.quote, f"Prompt {short_pid(r.prompt.id)} - {r.response.provider} - response {r.response.id}")
            cols = st.columns([1, 1, 2])
            cols[0].markdown(f"**Claimed** {c.claimed_value}")
            cols[1].markdown(f"**Catalogue** {c.trusted_value}")
            cols[2].markdown(" ".join([source_tag(r.response.source_kind)] + [f'<a href="{u.url}">{u.domain}</a>' for u in r.response.citations[:3]]), unsafe_allow_html=True)
            with st.popover("View full answer"):
                raw_block("Raw answer - immutable", r.response.text)

    left, right = st.columns(2)
    with left:
        section("Strengths", "positive descriptions")
        pos = [(r, x) for r, x in mentions if x.sentiment == Sentiment.positive]
        if not pos:
            empty_state("No positive descriptions")
        for r, x in pos[:4]:
            quote(x.evidence_quote, f"{short_pid(r.prompt.id)} - {r.response.provider}" + (f" - {', '.join(x.attributes)}" if x.attributes else ""))
    with right:
        section("Concerns", "negative or hedged descriptions")
        weak = [(r, x) for r, x in mentions if x.sentiment in (Sentiment.negative, Sentiment.uncertain)]
        if not weak:
            empty_state("No negative or hedged descriptions")
        for r, x in weak[:4]:
            quote(x.evidence_quote, f"{short_pid(r.prompt.id)} - {r.response.provider} - {x.sentiment.value}")

    with st.expander("All extracted claims"):
        rows = [{"status": c.verification_status.value, "attribute": c.attribute, "product": c.product or "(brand-level)", "claimed": c.claimed_value, "catalogue": c.trusted_value or "-",
                 "prompt": short_pid(r.prompt.id), "provider": r.response.provider, "quote": c.quote} for r in records for c in r.extraction.claims]
        if rows:
            order = {"conflict": 0, "unverifiable": 1, "inconclusive": 2, "verified": 3}
            df = pd.DataFrame(rows).sort_values("status", key=lambda s: s.map(order))
            df_table(df, column_config={"quote": st.column_config.TextColumn(width="large")})
            st.caption(f"Verified against the uploaded catalogue, which may itself be outdated. {m.unverifiable_claims} claims could not be matched to a product.")
        else:
            empty_state("No claims extracted")
