"""Gap registry load — HTTP with cache fallback."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

from service_scout.config import ScoutConfig, TargetConfig

log = logging.getLogger(__name__)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gap_registry(cfg: ScoutConfig, target: TargetConfig | None = None) -> dict[str, Any]:
    """Fetch gaps artifact; on failure use cache; else committed default."""
    root = cfg.config_dir
    cache_path = Path(cfg.gaps.cache_path)
    if not cache_path.is_absolute():
        cache_path = root / cache_path
    default_path = Path(cfg.gaps.default_path)
    if not default_path.is_absolute():
        default_path = root / default_path

    url = (target.gaps_url if target and target.gaps_url else "") or cfg.gaps.source_url

    if url:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            log.info("gap_registry_fetched", extra={"url": url})
            return data
        except Exception as exc:  # noqa: BLE001 — fallback is intentional
            log.warning("gap_registry_fetch_failed: %s", exc)

    if cache_path.is_file():
        log.info("gap_registry_cache_hit path=%s", cache_path)
        return _read_json(cache_path)

    if default_path.is_file():
        log.info("gap_registry_default path=%s", default_path)
        return _read_json(default_path)

    raise RuntimeError("gap_registry_unavailable")


def open_gap_seeds(registry: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return (gap_id, description, query_seed) for open gaps."""
    out: list[tuple[str, str, str]] = []
    for section in ("scoring_gaps", "infra_constraints"):
        for item in registry.get(section) or []:
            if item.get("status") not in (None, "open"):
                continue
            gid = item.get("id") or "unknown"
            desc = item.get("description") or ""
            for seed in item.get("query_seeds") or []:
                out.append((gid, desc, seed))
    for seed in registry.get("source_health_seeds") or []:
        out.append(("source_health", "source health watch", seed))
    return out


def mark_gap_status(
    registry: dict[str, Any],
    gap_id: str,
    status: str,
    *,
    blocked_reason: str | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Update gap status in-memory and optionally re-cache."""
    from datetime import date

    today = date.today().isoformat()
    for section in ("scoring_gaps", "infra_constraints"):
        for item in registry.get(section) or []:
            if item.get("id") == gap_id:
                item["status"] = status
                item["blocked_reason"] = blocked_reason
                item["last_checked"] = today
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry
