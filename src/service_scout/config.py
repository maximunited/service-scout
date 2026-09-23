"""Load and validate Scout configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    url: str | None = None
    sqlite_path: str = "data/scout.db"


class TavilyPerRun(BaseModel):
    market_data: int = 3
    source_health: int = 3
    infra: int = 2


class TavilyEscalation(BaseModel):
    enabled: bool = True
    monthly_extra_searches: int = 4
    min_uncertainty: int = 3
    require_reason: bool = True
    max_extra_per_candidate: int = 1
    allow_advanced_depth: bool = False
    allow_research_endpoint: bool = False
    max_suggested_queries: int = 2


class TavilyConfig(BaseModel):
    api_key: str = ""
    monthly_credit_budget: int = 50
    reserved_for_cursor_mcp: int = 200
    search_depth: str = "basic"
    max_results: int = 5
    per_run: TavilyPerRun = Field(default_factory=TavilyPerRun)
    escalation: TavilyEscalation = Field(default_factory=TavilyEscalation)


class OllamaConfig(BaseModel):
    base_url: str = ""
    model: str = ""
    api_token: str = ""
    temperature: float = 0.2
    retry_temperature: float = 0.3
    json_repair_retries: int = 1


class NotionOutcome(BaseModel):
    status: str = "Backlog"
    refinement: str = "Raw"


class NotionProperties(BaseModel):
    status: str = "Status"
    refinement: str = "Refinement"
    source: str = "Source"
    scout_verdict: str = "Scout verdict"
    scout_lane: str = "Scout lane"
    scout_service_id: str = "Scout service_id"
    free_tier: str = "Free tier"
    confidence: str = "Confidence"


class NotionConfig(BaseModel):
    token: str = ""
    roadmap_data_source: str = ""
    on_revisit: str = "update_existing"
    properties: NotionProperties = Field(default_factory=NotionProperties)
    on_accept: NotionOutcome = Field(default_factory=NotionOutcome)
    on_needs_research: NotionOutcome = Field(default_factory=NotionOutcome)
    on_reject: NotionOutcome = Field(
        default_factory=lambda: NotionOutcome(status="Rejected", refinement="Raw")
    )
    source_value: str = "Agent"
    priority_default: str = "P3"


class DigestConfig(BaseModel):
    enabled: bool = True
    apprise_urls: list[str] = Field(default_factory=list)
    include_rejects: bool = False
    include_needs_research: bool = True
    max_items: int = 20
    immediate_accept_min_confidence: int = 5


class GovernorConfig(BaseModel):
    max_tool_rounds: int = 2
    min_uncertainty_to_escalate: int = 3
    commit_threshold: int = 3


class DedupeConfig(BaseModel):
    query_notion_statuses: list[str] = Field(
        default_factory=lambda: [
            "Backlog",
            "In Progress",
            "Done",
            "Deferred",
            "Rejected",
        ]
    )


class GapsConfig(BaseModel):
    source_url: str = ""
    cache_path: str = "data/gaps_cache.json"
    default_path: str = "gaps.default.json"


class BrainConfig(BaseModel):
    enabled: bool = False
    api_url: str = ""
    token: str = ""


class LaneToggle(BaseModel):
    enabled: bool = True
    free_tier_only: bool = True
    prefer_rss: bool = True
    rss_feeds: list[str] = Field(default_factory=list)


class TargetConfig(BaseModel):
    id: str
    gaps_url: str = ""
    notion_data_source: str = ""
    lanes: list[str] = Field(
        default_factory=lambda: ["market_data", "source_health", "infra"]
    )


class OverridesConfig(BaseModel):
    force_reject_domains: list[str] = Field(default_factory=list)
    force_watch_vendors: list[str] = Field(default_factory=list)
    always_include_query_seeds: list[str] = Field(default_factory=list)
    alias_merges: dict[str, str] = Field(default_factory=dict)


class ScoutConfig(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    notion: NotionConfig = Field(default_factory=NotionConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    governor: GovernorConfig = Field(default_factory=GovernorConfig)
    dedupe: DedupeConfig = Field(default_factory=DedupeConfig)
    gaps: GapsConfig = Field(default_factory=GapsConfig)
    brain: BrainConfig = Field(default_factory=BrainConfig)
    autotune: dict[str, Any] = Field(default_factory=lambda: {"enabled": False})
    lanes: dict[str, LaneToggle] = Field(default_factory=dict)
    targets: list[TargetConfig] = Field(default_factory=list)
    overrides: OverridesConfig = Field(default_factory=OverridesConfig)
    config_dir: Path = Field(default_factory=lambda: Path("."))

    def resolve_secrets(self) -> None:
        """Fill empty secrets from environment."""
        if not self.tavily.api_key:
            self.tavily.api_key = os.environ.get("TAVILY_API_KEY", "")
        if not self.ollama.base_url:
            self.ollama.base_url = os.environ.get("OLLAMA_BASE_URL", "")
        if not self.ollama.model:
            self.ollama.model = os.environ.get("OLLAMA_MODEL", "")
        if not self.ollama.api_token:
            self.ollama.api_token = os.environ.get("OLLAMA_API_TOKEN", "")
        if not self.notion.token:
            self.notion.token = os.environ.get("NOTION_TOKEN", "") or os.environ.get(
                "NOTION_API_KEY", ""
            )
        if not self.brain.token:
            self.brain.token = os.environ.get("BRAIN_API_TOKEN", "")
        if not self.database.url:
            self.database.url = os.environ.get("SCOUT_DATABASE_URL")


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> ScoutConfig:
    """Load config.example.yaml defaults, then config.yaml, then overrides.yaml."""
    root = Path(path).resolve().parent if path else Path.cwd()
    if path:
        cfg_path = Path(path)
        root = cfg_path.parent
    else:
        cfg_path = root / "config.yaml"

    data: dict[str, Any] = {}
    example = root / "config.example.yaml"
    if example.is_file():
        data = yaml.safe_load(example.read_text(encoding="utf-8")) or {}

    if cfg_path.is_file():
        overlay = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        data = _deep_merge(data, overlay)

    overrides_path = root / "overrides.yaml"
    overrides_data: dict[str, Any] = {}
    if overrides_path.is_file():
        overrides_data = yaml.safe_load(overrides_path.read_text(encoding="utf-8")) or {}

    # Normalize lane entries that may be bare dicts
    lanes_raw = data.get("lanes") or {}
    lanes: dict[str, Any] = {}
    for name, val in lanes_raw.items():
        if isinstance(val, bool):
            lanes[name] = {"enabled": val}
        else:
            lanes[name] = val
    data["lanes"] = lanes

    cfg = ScoutConfig.model_validate(data)
    if overrides_data:
        cfg.overrides = OverridesConfig.model_validate(overrides_data)
    cfg.config_dir = root
    cfg.resolve_secrets()

    if not cfg.targets:
        cfg.targets = [
            TargetConfig(
                id="portfolio-advisor",
                lanes=["market_data", "source_health", "infra"],
            )
        ]
    if not cfg.lanes:
        cfg.lanes = {
            "market_data": LaneToggle(enabled=True),
            "source_health": LaneToggle(enabled=True),
            "infra": LaneToggle(
                enabled=True,
                rss_feeds=[
                    "https://news.ycombinator.com/rss",
                    "https://lobste.rs/rss",
                ],
            ),
        }
    return cfg
