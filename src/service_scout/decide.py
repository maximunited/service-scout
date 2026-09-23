"""Persist verdict → Notion + AgDR + digest queue."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_scout.config import ScoutConfig, TargetConfig
from service_scout.db import (
    AgentDecisionRecord,
    DigestQueueItem,
    NotionLink,
    dumps,
)
from service_scout.models import AgentVerdict, ScoutNotionVerdict
from service_scout.tools import notion as notion_tool
from service_scout.tools.apprise_digest import send_apprise

log = logging.getLogger(__name__)


def agent_to_notion_verdict(
    v: AgentVerdict, *, forced: ScoutNotionVerdict | None = None
) -> ScoutNotionVerdict:
    if forced:
        return forced
    if v.verdict == "accept":
        return "accept"
    if v.verdict == "reject":
        return "reject"
    return "needs_research"


def apply_free_first_gates(
    v: AgentVerdict,
    *,
    lane: str,
) -> ScoutNotionVerdict:
    """Downgrade accept if free-first / hook gates fail."""
    if v.verdict == "need_more":
        return "needs_research"
    if v.verdict == "reject":
        return "reject"
    # accept
    if not v.free_tier_summary:
        return "needs_research"
    if lane in ("market_data", "source_health") and not v.scoring_or_infra_hook:
        return "needs_research"
    if lane == "infra" and not v.scoring_or_infra_hook and not v.free_tier_summary:
        return "needs_research"
    # paid-only keyword sniff
    ft = (v.free_tier_summary or "").lower()
    if "no free" in ft or "paid only" in ft or "paid-only" in ft:
        return "reject"
    return "accept"


def _queue_digest(
    session: Session,
    *,
    service_id: str,
    title: str,
    scout_verdict: str,
    notion_page_id: str,
    url: str,
) -> None:
    """Upsert one unflushed digest row per service_id (no duplicates)."""
    existing = session.scalars(
        select(DigestQueueItem).where(
            DigestQueueItem.service_id == service_id,
            DigestQueueItem.flushed == 0,
        )
    ).first()
    if existing:
        existing.title = title
        existing.scout_verdict = scout_verdict
        existing.notion_page_id = notion_page_id
        existing.url = url
        return
    session.add(
        DigestQueueItem(
            service_id=service_id,
            title=title,
            scout_verdict=scout_verdict,
            notion_page_id=notion_page_id,
            url=url,
        )
    )


def write_agdr(
    session: Session,
    *,
    run_id: str,
    service_id: str,
    fingerprint: str,
    verdict: str,
    queries_run: list,
    tool_calls: list,
    constraints_checked: list,
    raw: str,
    validation_error: str,
    commit: bool = False,
) -> None:
    """Append AgDR. Caller commits after Notion succeeds unless commit=True."""
    session.add(
        AgentDecisionRecord(
            run_id=run_id,
            service_id=service_id,
            candidate_fingerprint=fingerprint,
            verdict=verdict,
            queries_run=dumps(queries_run),
            tool_calls=dumps(tool_calls),
            constraints_checked=dumps(constraints_checked),
            raw_agent_output=raw[:8000],
            validation_error=(validation_error or "")[:2000],
        )
    )
    if commit:
        session.commit()


def persist_decision(
    session: Session,
    cfg: ScoutConfig,
    target: TargetConfig,
    *,
    run_id: str,
    service_id: str,
    name: str,
    url: str,
    lane: str,
    notion_verdict: ScoutNotionVerdict,
    agent: AgentVerdict | None,
    queries_run: list,
    tool_calls: list,
    constraints_checked: list,
    raw: str,
    validation_error: str,
    dry_run: bool = False,
) -> str | None:
    fingerprint = f"{service_id}|{url}"

    free_tier = agent.free_tier_summary if agent else None
    hook = agent.scoring_or_infra_hook if agent else None
    reason = None
    if agent:
        reason = agent.reject_reason or agent.why_more_search
    if notion_verdict == "reject" and validation_error and not reason:
        reason = "invalid_agent_output"
    open_q = list(agent.open_questions) if agent else []
    confidence = agent.confidence if agent else None

    body = notion_tool.build_page_body(
        name=name,
        url=url,
        lane=lane,
        verdict=notion_verdict,
        free_tier=free_tier,
        hook=hook,
        reason=reason,
        open_questions=open_q,
        confidence=confidence,
        service_id=service_id,
    )
    title = name or service_id

    if dry_run:
        log.info(
            "dry_run notion %s",
            notion_tool.dry_run_payload(title=title, body=body, verdict=notion_verdict),
        )
        write_agdr(
            session,
            run_id=run_id,
            service_id=service_id,
            fingerprint=fingerprint,
            verdict=notion_verdict,
            queries_run=queries_run,
            tool_calls=tool_calls,
            constraints_checked=constraints_checked,
            raw=raw,
            validation_error=validation_error,
            commit=True,
        )
        return None

    existing = session.get(NotionLink, service_id)
    page_id = existing.notion_page_id if existing else None
    if existing and cfg.notion.on_revisit == "skip":
        log.info("notion_skip_existing service_id=%s", service_id)
        write_agdr(
            session,
            run_id=run_id,
            service_id=service_id,
            fingerprint=fingerprint,
            verdict=notion_verdict,
            queries_run=queries_run,
            tool_calls=tool_calls,
            constraints_checked=constraints_checked + ["notion_skip_existing"],
            raw=raw,
            validation_error=validation_error,
            commit=True,
        )
        return page_id

    # Notion first — AgDR only after a successful write
    ds = target.notion_data_source or cfg.notion.roadmap_data_source
    page_id = notion_tool.create_or_update_page(
        cfg.notion,
        data_source=ds,
        title=title,
        body=body,
        verdict=notion_verdict,
        lane=lane,
        service_id=service_id,
        free_tier=free_tier,
        confidence=confidence,
        existing_page_id=page_id,
    )

    link = existing or NotionLink(service_id=service_id)
    link.notion_page_id = page_id or ""
    link.scout_verdict = notion_verdict
    link.last_updated = datetime.now(timezone.utc)
    session.merge(link)
    _queue_digest(
        session,
        service_id=service_id,
        title=title,
        scout_verdict=notion_verdict,
        notion_page_id=page_id or "",
        url=url,
    )
    write_agdr(
        session,
        run_id=run_id,
        service_id=service_id,
        fingerprint=fingerprint,
        verdict=notion_verdict,
        queries_run=queries_run,
        tool_calls=tool_calls,
        constraints_checked=constraints_checked,
        raw=raw,
        validation_error=validation_error,
        commit=False,
    )
    session.commit()

    # Immediate high-confidence accept notify
    if (
        notion_verdict == "accept"
        and confidence is not None
        and confidence >= cfg.digest.immediate_accept_min_confidence
        and cfg.digest.apprise_urls
    ):
        send_apprise(
            cfg.digest.apprise_urls,
            title=f"Scout accept: {title}",
            body=f"{url}\n{hook or ''}\n{free_tier or ''}",
        )
    return page_id
