"""Notion Roadmap create / update for Scout verdicts."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from service_scout.config import NotionConfig
from service_scout.models import ScoutNotionVerdict

log = logging.getLogger(__name__)

NOTION_VERSION = "2022-06-28"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _data_source_id(raw: str) -> str:
    """Accept collection://UUID or bare UUID."""
    s = (raw or "").strip()
    m = re.search(r"([0-9a-fA-F-]{32,36})", s)
    return m.group(1) if m else s.replace("collection://", "")


def _rich_text(content: str) -> list[dict[str, Any]]:
    # Notion rich_text chunk limit ~2000
    text = (content or "")[:1900]
    return [{"type": "text", "text": {"content": text}}]


def _title(content: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": (content or "Untitled")[:200]}}]


def build_page_body(
    *,
    name: str,
    url: str,
    lane: str,
    verdict: ScoutNotionVerdict,
    free_tier: str | None,
    hook: str | None,
    reason: str | None,
    open_questions: list[str],
    confidence: int | None,
    service_id: str,
) -> str:
    """Short paraphrase notes — not copyrighted dumps."""
    lines = [
        f"**Scout verdict:** `{verdict}`",
        f"**Service:** {name}",
        f"**URL:** {url}",
        f"**Lane:** {lane}",
        f"**service_id:** `{service_id}`",
    ]
    if free_tier:
        lines.append(f"**Free tier (summary):** {free_tier[:500]}")
    if hook:
        lines.append(f"**Scoring / infra hook:** {hook[:500]}")
    if reason:
        lines.append(f"**Reason:** {reason[:500]}")
    if open_questions:
        lines.append("**Open questions:**")
        for q in open_questions[:8]:
            lines.append(f"- {q[:200]}")
    if confidence is not None:
        lines.append(f"**Confidence:** {confidence}/5")
    lines.append("")
    lines.append(
        "_Internal research note — URLs and paraphrased facts only; not a republication of vendor docs._"
    )
    return "\n".join(lines)


def create_or_update_page(
    cfg: NotionConfig,
    *,
    data_source: str,
    title: str,
    body: str,
    verdict: ScoutNotionVerdict,
    lane: str,
    service_id: str,
    free_tier: str | None,
    confidence: int | None,
    existing_page_id: str | None = None,
) -> str:
    if not cfg.token:
        raise RuntimeError("notion_token_missing")

    ds = _data_source_id(data_source or cfg.roadmap_data_source)
    outcome = {
        "accept": cfg.on_accept,
        "needs_research": cfg.on_needs_research,
        "reject": cfg.on_reject,
    }[verdict]

    display_title = title
    if verdict == "needs_research" and not title.startswith("[Needs research]"):
        display_title = f"[Needs research] {title}"

    props: dict[str, Any] = {
        "Name": {"title": _title(display_title)},
        cfg.properties.status: {
            "select": {"name": outcome.status},
        },
        cfg.properties.refinement: {
            "select": {"name": outcome.refinement},
        },
        cfg.properties.source: {
            "select": {"name": cfg.source_value},
        },
    }
    # Optional Scout properties — ignore if DB doesn't have them (caller may strip)
    optional = {
        cfg.properties.scout_verdict: {"select": {"name": verdict}},
        cfg.properties.scout_lane: {"rich_text": _rich_text(lane)},
        cfg.properties.scout_service_id: {"rich_text": _rich_text(service_id)},
    }
    if free_tier:
        optional[cfg.properties.free_tier] = {"rich_text": _rich_text(free_tier[:200])}
    if confidence is not None:
        optional[cfg.properties.confidence] = {"number": confidence}

    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(body)},
        }
    ]

    with httpx.Client(timeout=30.0, headers=_headers(cfg.token)) as client:
        if existing_page_id and cfg.on_revisit == "update_existing":
            # Update properties + append a paragraph
            for attempt_props in ( {**props, **optional}, props):
                r = client.patch(
                    f"https://api.notion.com/v1/pages/{existing_page_id}",
                    json={"properties": attempt_props},
                )
                if r.status_code < 300:
                    break
            client.patch(
                f"https://api.notion.com/v1/blocks/{existing_page_id}/children",
                json={
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": _rich_text(f"Update:\n{body[:1500]}")
                            },
                        }
                    ]
                },
            )
            return existing_page_id

        # Create — try with optional props, fall back without
        parent = {"type": "data_source_id", "data_source_id": ds}
        # Also support database_id style parent for older integrations
        payloads = [
            {"parent": parent, "properties": {**props, **optional}, "children": children},
            {"parent": parent, "properties": props, "children": children},
            {
                "parent": {"database_id": ds},
                "properties": props,
                "children": children,
            },
        ]
        last_err = ""
        for payload in payloads:
            r = client.post("https://api.notion.com/v1/pages", json=payload)
            if r.status_code < 300:
                page_id = r.json().get("id", "")
                log.info("notion_page_created id=%s verdict=%s", page_id, verdict)
                return page_id
            last_err = r.text[:500]
            log.warning("notion_create_attempt_failed: %s", last_err)
        raise RuntimeError(f"notion_create_failed: {last_err}")


def dry_run_payload(
    *,
    title: str,
    body: str,
    verdict: ScoutNotionVerdict,
) -> dict[str, Any]:
    return {"title": title, "verdict": verdict, "body": body[:500]}
