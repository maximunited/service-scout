"""Feedback helpers — AgDR sampling + notion link refresh placeholders."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_scout.db import AgentDecisionRecord, NotionLink

log = logging.getLogger(__name__)


def recent_verdict_examples(session: Session, limit: int = 10) -> list[dict]:
    rows = session.scalars(
        select(AgentDecisionRecord).order_by(AgentDecisionRecord.id.desc()).limit(limit)
    ).all()
    return [
        {
            "service_id": r.service_id,
            "verdict": r.verdict,
            "validation_error": r.validation_error,
        }
        for r in rows
    ]


def list_notion_links(session: Session) -> list[NotionLink]:
    return list(session.scalars(select(NotionLink)).all())
