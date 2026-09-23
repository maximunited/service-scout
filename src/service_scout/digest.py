"""Weekly digest flush via Apprise."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_scout.config import ScoutConfig
from service_scout.db import DigestQueueItem
from service_scout.tools.apprise_digest import send_apprise

log = logging.getLogger(__name__)


def flush_digest(session: Session, cfg: ScoutConfig) -> int:
    if not cfg.digest.enabled:
        return 0
    rows = session.scalars(
        select(DigestQueueItem)
        .where(DigestQueueItem.flushed == 0)
        .order_by(DigestQueueItem.created_at.asc())
        .limit(cfg.digest.max_items)
    ).all()
    if not rows:
        log.info("digest_empty")
        return 0

    lines: list[str] = []
    kept = 0
    for r in rows:
        if r.scout_verdict == "reject" and not cfg.digest.include_rejects:
            r.flushed = 1
            continue
        if r.scout_verdict == "needs_research" and not cfg.digest.include_needs_research:
            r.flushed = 1
            continue
        lines.append(f"- [{r.scout_verdict}] {r.title} — {r.url}")
        r.flushed = 1
        kept += 1
    session.commit()
    if not lines:
        return 0
    body = "Service Scout weekly digest\n\n" + "\n".join(lines)
    send_apprise(cfg.digest.apprise_urls, title="Service Scout digest", body=body)
    return kept
