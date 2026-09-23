"""Unit tests — no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from service_scout.config import load_config
from service_scout.db import init_db, make_engine
from service_scout.dedupe import make_service_id, normalize_domain, resolve_service_id
from service_scout.gaps import load_gap_registry, open_gap_seeds
from service_scout.governor import Governor
from service_scout.models import AgentVerdict, LaneResult
from service_scout.decide import apply_free_first_gates


ROOT = Path(__file__).resolve().parents[1]


def test_agent_verdict_schema():
    v = AgentVerdict.model_validate(
        {
            "verdict": "accept",
            "uncertainty": 2,
            "confidence": 4,
            "free_tier_summary": "1000 credits/mo",
            "scoring_or_infra_hook": "composite valuation",
        }
    )
    assert v.verdict == "accept"


def test_agent_verdict_rejects_bad():
    with pytest.raises(ValidationError):
        AgentVerdict.model_validate({"verdict": "maybe", "uncertainty": 9})


def test_normalize_domain():
    assert normalize_domain("https://docs.Example.com/api") == "example.com"
    assert normalize_domain("www.Foo.io") == "foo.io"


def test_free_first_gates_needs_research_without_tier():
    v = AgentVerdict(verdict="accept", confidence=4, uncertainty=2, scoring_or_infra_hook="x")
    assert apply_free_first_gates(v, lane="market_data") == "needs_research"


def test_free_first_gates_accept():
    v = AgentVerdict(
        verdict="accept",
        confidence=4,
        uncertainty=2,
        free_tier_summary="500 req/day free",
        scoring_or_infra_hook="score_valuation",
    )
    assert apply_free_first_gates(v, lane="market_data") == "accept"


def test_gap_registry_default(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg = load_config(str(ROOT / "config.example.yaml"))
    cfg.config_dir = ROOT
    cfg.gaps.source_url = ""
    cfg.gaps.cache_path = str(tmp_path / "cache.json")
    reg = load_gap_registry(cfg)
    assert "scoring_gaps" in reg
    seeds = open_gap_seeds(reg)
    assert seeds


def test_governor_budget(tmp_path):
    from service_scout.config import ScoutConfig, DatabaseConfig, TavilyConfig

    cfg = ScoutConfig(
        database=DatabaseConfig(sqlite_path=str(tmp_path / "t.db")),
        tavily=TavilyConfig(monthly_credit_budget=5, reserved_for_cursor_mcp=0),
    )
    engine = make_engine(cfg.database)
    Session = init_db(engine)
    with Session() as s:
        g = Governor(cfg, s)
        assert g.can_spend(5)
        g.record_spend(3)
        assert g.snapshot().tavily_remaining == 2
        assert not g.can_spend(3)


def test_alias_dedupe(tmp_path):
    from service_scout.config import ScoutConfig, DatabaseConfig

    cfg = ScoutConfig(database=DatabaseConfig(sqlite_path=str(tmp_path / "a.db")))
    engine = make_engine(cfg.database)
    Session = init_db(engine)
    with Session() as s:
        a = resolve_service_id(s, name="Acme API", url="https://acme.com/pricing")
        b = resolve_service_id(s, name="Acme Data", url="https://docs.acme.com/intro")
        assert a == b


def test_lane_result_shape():
    lr: LaneResult = {
        "queries": [],
        "credits_reserved": 0,
        "blocked_reason": "no_new_candidates",
        "partial_failures": [],
    }
    assert lr["blocked_reason"]


def test_make_service_id_stable():
    assert make_service_id("X", "https://x.com") == make_service_id("X", "https://x.com/")
