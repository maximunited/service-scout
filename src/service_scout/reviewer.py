"""Optional second-pass ingestibility reviewer (gated; off by default).

Differs from governor (budget) and Ollama first pass (triage):
adversarial check — \"is this actually a free machine-ingestible data source?\"
Cheap rules run first; optional Ollama only when enabled and rules are inconclusive.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from service_scout.classify import has_ingest_evidence, is_content_only_url, is_denylisted
from service_scout.config import OverridesConfig
from service_scout.models import AgentVerdict, ScoutNotionVerdict

log = logging.getLogger(__name__)


@dataclass
class ReviewerConfig:
    """Wire into ScoutConfig when enabling the stage."""

    enabled: bool = False
    use_ollama: bool = False  # keep False until budget + prompt eval exist
    max_ollama_reviews_per_run: int = 2


@dataclass
class ReviewResult:
    verdict: ScoutNotionVerdict | None  # None = no change
    reason: str
    used_ollama: bool = False


def review_before_notion(
    *,
    url: str,
    title: str,
    snippets: list[str],
    agent: AgentVerdict,
    proposed: ScoutNotionVerdict,
    overrides: OverridesConfig | None = None,
    cfg: ReviewerConfig | None = None,
) -> ReviewResult:
    """
    Second-pass gate before Notion write.

    When disabled: no-op (returns proposed unchanged via verdict=None).
    Rules-only path: downgrade accept / needs_research → reject for content-only
    or missing ingest evidence. Does not call Ollama unless cfg.use_ollama.
    """
    cfg = cfg or ReviewerConfig()
    if not cfg.enabled:
        return ReviewResult(verdict=None, reason="reviewer_disabled")

    if proposed == "reject":
        return ReviewResult(verdict=None, reason="already_reject")

    if is_denylisted(url, overrides) or is_content_only_url(url, title=title):
        return ReviewResult(verdict="reject", reason="reviewer_content_or_denylist")

    blob = " ".join(
        [
            title or "",
            agent.free_tier_summary or "",
            agent.scoring_or_infra_hook or "",
            *(snippets or []),
        ]
    )
    if proposed == "accept" and not has_ingest_evidence(blob):
        return ReviewResult(verdict="reject", reason="reviewer_no_ingest_evidence")

    if proposed == "needs_research" and is_content_only_url(url, title=title):
        return ReviewResult(verdict="reject", reason="content_only_no_api")

    # Optional Ollama adversarial pass — stubbed (not implemented).
    if cfg.use_ollama:
        log.debug("reviewer_ollama_stub skipped url=%s", url)
        return ReviewResult(verdict=None, reason="reviewer_ollama_stub", used_ollama=False)

    return ReviewResult(verdict=None, reason="reviewer_pass")
