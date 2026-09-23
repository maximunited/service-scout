"""Lane plugins — return LaneResult contracts."""

from __future__ import annotations

from typing import Any, Callable

from service_scout.config import LaneToggle, ScoutConfig
from service_scout.gaps import open_gap_seeds
from service_scout.governor import Governor
from service_scout.models import LaneResult, Query
from service_scout.tools.rss import fetch_rss_hits


def _lane_enabled(cfg: ScoutConfig, name: str) -> LaneToggle:
    return cfg.lanes.get(name) or LaneToggle(enabled=True)


def run_market_data(
    registry: dict[str, Any],
    cfg: ScoutConfig,
    governor: Governor,
) -> LaneResult:
    toggle = _lane_enabled(cfg, "market_data")
    if not toggle.enabled:
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="lane_disabled", partial_failures=[])
    if not governor.can_spend(1):
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="budget", partial_failures=[])

    cap = cfg.tavily.per_run.market_data
    scoring_ids = {g.get("id") for g in (registry.get("scoring_gaps") or [])}
    queries: list[Query] = []
    seen: set[str] = set()
    for gid, _desc, seed in open_gap_seeds(registry):
        if gid not in scoring_ids:
            continue
        if seed in seen:
            continue
        seen.add(seed)
        queries.append(Query(text=seed, lane="market_data", gap_id=gid, source="gap_seed"))
        if len(queries) >= cap:
            break

    for seed in cfg.overrides.always_include_query_seeds:
        if len(queries) >= cap:
            break
        if seed in seen:
            continue
        queries.append(Query(text=seed, lane="market_data", gap_id=None, source="override"))

    if not queries:
        return LaneResult(
            queries=[],
            credits_reserved=0,
            blocked_reason="no_new_candidates",
            partial_failures=[],
        )
    return LaneResult(
        queries=queries[:cap],
        credits_reserved=min(cap, len(queries)),
        blocked_reason=None,
        partial_failures=[],
    )


def run_source_health(
    registry: dict[str, Any],
    cfg: ScoutConfig,
    governor: Governor,
) -> LaneResult:
    toggle = _lane_enabled(cfg, "source_health")
    if not toggle.enabled:
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="lane_disabled", partial_failures=[])
    if not governor.can_spend(1):
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="budget", partial_failures=[])

    cap = cfg.tavily.per_run.source_health
    queries: list[Query] = []
    for seed in registry.get("source_health_seeds") or []:
        queries.append(Query(text=seed, lane="source_health", gap_id="source_health", source="gap_seed"))
        if len(queries) >= cap:
            break
    if not queries:
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="no_new_candidates", partial_failures=[])
    return LaneResult(
        queries=queries,
        credits_reserved=len(queries),
        blocked_reason=None,
        partial_failures=[],
    )


def run_infra(
    registry: dict[str, Any],
    cfg: ScoutConfig,
    governor: Governor,
) -> LaneResult:
    toggle = _lane_enabled(cfg, "infra")
    if not toggle.enabled:
        return LaneResult(queries=[], credits_reserved=0, blocked_reason="lane_disabled", partial_failures=[])

    partial: list[str] = []
    queries: list[Query] = []

    # RSS first (zero Tavily)
    if toggle.prefer_rss and toggle.rss_feeds:
        try:
            hits = fetch_rss_hits(toggle.rss_feeds)
            for h in hits[:5]:
                title = h.get("title") or ""
                url = h.get("url") or ""
                if not url:
                    continue
                queries.append(
                    Query(
                        text=f"{title} {url}",
                        lane="infra",
                        gap_id="neon_cu_limit",
                        source="rss",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            partial.append(f"rss_fetch:{exc}")

    cap = cfg.tavily.per_run.infra
    # Optional Tavily seeds from open infra constraints
    tavily_queries: list[Query] = []
    for item in registry.get("infra_constraints") or []:
        if item.get("status") not in (None, "open"):
            continue
        for seed in item.get("query_seeds") or []:
            tavily_queries.append(
                Query(text=seed, lane="infra", gap_id=item.get("id"), source="gap_seed")
            )
            if len(tavily_queries) >= cap:
                break
        if len(tavily_queries) >= cap:
            break

    credits = 0
    if tavily_queries and governor.can_spend(len(tavily_queries)):
        queries.extend(tavily_queries)
        credits = len(tavily_queries)
    elif tavily_queries and not governor.can_spend(1):
        partial.append("tavily_budget_skipped")

    if not queries:
        return LaneResult(
            queries=[],
            credits_reserved=0,
            blocked_reason="no_new_candidates",
            partial_failures=partial,
        )
    return LaneResult(
        queries=queries,
        credits_reserved=credits,
        blocked_reason=None,
        partial_failures=partial,
    )


LANE_RUNNERS: dict[str, Callable[..., LaneResult]] = {
    "market_data": run_market_data,
    "source_health": run_source_health,
    "infra": run_infra,
}


def run_lane(name: str, registry: dict[str, Any], cfg: ScoutConfig, governor: Governor) -> LaneResult:
    fn = LANE_RUNNERS.get(name)
    if not fn:
        return LaneResult(
            queries=[],
            credits_reserved=0,
            blocked_reason=f"unknown_lane:{name}",
            partial_failures=[],
        )
    return fn(registry, cfg, governor)
