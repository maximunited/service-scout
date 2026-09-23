"""RSS fetch for infra lane (zero Tavily when possible)."""

from __future__ import annotations

import logging
from typing import Any

import feedparser

from service_scout.models import SearchHit

log = logging.getLogger(__name__)

INFRA_KEYWORDS = (
    "postgres",
    "postgresql",
    "redis",
    "database",
    "neon",
    "turso",
    "supabase",
    "planetscale",
    "free tier",
    "serverless",
    "kv store",
    "upstash",
)


def fetch_rss_hits(feed_urls: list[str], *, limit_per_feed: int = 15) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
            for entry in (parsed.entries or [])[:limit_per_feed]:
                title = getattr(entry, "title", "") or ""
                link = getattr(entry, "link", "") or ""
                summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
                blob = f"{title} {summary}".lower()
                if not any(k in blob for k in INFRA_KEYWORDS):
                    continue
                hits.append(
                    SearchHit(
                        title=title[:200],
                        url=link,
                        content=summary[:500],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("rss_fetch_failed url=%s err=%s", url, exc)
    return hits
