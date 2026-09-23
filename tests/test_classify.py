"""URL classifier + denylist + ingest-evidence gates."""

from __future__ import annotations

from service_scout.classify import (
    classify_candidate,
    has_ingest_evidence,
    is_content_only_url,
    is_denylisted,
)
from service_scout.config import OverridesConfig
from service_scout.models import AgentVerdict
from service_scout.reviewer import ReviewerConfig, review_before_notion


def test_denylist_tikr_quant_damodaran():
    assert is_denylisted("https://www.tikr.com/terminal")
    assert is_denylisted("https://quant-investing.com/guides/fcf")
    assert is_denylisted("https://aswathdamodaran.substack.com/p/foo")


def test_denylist_respects_overrides():
    ov = OverridesConfig(force_reject_domains=["example-scam.com"])
    assert is_denylisted("https://api.example-scam.com/v1", ov)


def test_content_only_substack_and_guide_path():
    assert is_content_only_url("https://foo.substack.com/p/bar")
    assert is_content_only_url("https://vendor.com/academy/fcf-primer")
    assert is_content_only_url("https://vendor.com/blog/cash-flow")
    assert not is_content_only_url("https://finnhub.io/docs/api")


def test_ingest_evidence_required():
    assert has_ingest_evidence("public REST API free tier 100/day")
    assert has_ingest_evidence("GraphQL endpoint free key")
    assert has_ingest_evidence("scrapable public JSON pattern")
    assert not has_ingest_evidence("free tools to analyze cash flow")
    assert not has_ingest_evidence("free account for web terminal")


def test_classify_pre_ollama_skips_content():
    c = classify_candidate(
        "https://aswathdamodaran.substack.com/p/fcf",
        title="Damodaran FCF primer",
    )
    assert c.skip_ollama
    assert c.reason in ("not_a_data_source", "denylist_domain")


def test_classify_pre_ollama_skips_tikr():
    c = classify_candidate(
        "https://www.tikr.com/",
        title="TIKR Terminal free account",
        snippets=["Sign up free for the research terminal"],
    )
    assert c.skip_ollama
    assert c.kind in ("denylist", "ui_only", "content_only")


def test_classify_allows_api_docs():
    c = classify_candidate(
        "https://finnhub.io/docs/api",
        title="Finnhub stock API",
        snippets=["REST API free tier 60 calls/minute"],
    )
    assert not c.skip_ollama
    assert c.kind == "candidate"


def test_reviewer_disabled_noop():
    agent = AgentVerdict(
        verdict="accept",
        confidence=4,
        uncertainty=2,
        free_tier_summary="REST API free",
        scoring_or_infra_hook="scores",
    )
    r = review_before_notion(
        url="https://example.com/api",
        title="Example",
        snippets=["REST API"],
        agent=agent,
        proposed="accept",
        cfg=ReviewerConfig(enabled=False),
    )
    assert r.verdict is None


def test_reviewer_rejects_accept_without_ingest():
    agent = AgentVerdict(
        verdict="accept",
        confidence=4,
        uncertainty=2,
        free_tier_summary="free account",
        scoring_or_infra_hook="UI charts",
    )
    r = review_before_notion(
        url="https://example.com/terminal",
        title="Example Terminal",
        snippets=["Sign up free for the dashboard"],
        agent=agent,
        proposed="accept",
        cfg=ReviewerConfig(enabled=True),
    )
    assert r.verdict == "reject"
    assert "ingest" in r.reason or "content" in r.reason or "denylist" in r.reason
