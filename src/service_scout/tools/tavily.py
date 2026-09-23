"""Tavily basic search tool."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from service_scout.models import SearchHit

log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"


def tavily_search(
    *,
    api_key: str,
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
) -> list[SearchHit]:
    if not api_key:
        raise RuntimeError("tavily_api_key_missing")
    if search_depth not in ("basic", "advanced"):
        search_depth = "basic"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": False,
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(TAVILY_URL, json=payload)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    hits: list[SearchHit] = []
    for r in data.get("results") or []:
        hits.append(
            SearchHit(
                title=r.get("title") or "",
                url=r.get("url") or "",
                content=(r.get("content") or "")[:800],
                score=float(r.get("score") or 0),
            )
        )
    log.info("tavily_search q=%r hits=%d", query[:80], len(hits))
    return hits


def credit_cost(search_depth: str) -> int:
    return 2 if search_depth == "advanced" else 1
