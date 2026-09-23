"""Main scout run loop."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from service_scout.agent import hits_to_snippets, triage_with_retry
from service_scout.config import ScoutConfig, TargetConfig
from service_scout.db import NotionLink, Run
from service_scout.decide import apply_free_first_gates, persist_decision
from service_scout.dedupe import is_force_rejected, normalize_domain, resolve_service_id
from service_scout.gaps import load_gap_registry
from service_scout.governor import Governor
from service_scout.lanes import run_lane
from service_scout.models import AgentVerdict, SearchHit
from service_scout.tools.apprise_digest import brain_append
from service_scout.tools.tavily import credit_cost, tavily_search

log = logging.getLogger(__name__)


def _cluster_hits(hits: list[SearchHit], lane: str) -> list[tuple[str, str, list[str]]]:
    """Group hits by domain → (name, url, snippets)."""
    by_domain: dict[str, list[SearchHit]] = {}
    for h in hits:
        dom = normalize_domain(h.get("url") or "") or "unknown"
        by_domain.setdefault(dom, []).append(h)
    out: list[tuple[str, str, list[str]]] = []
    for dom, group in by_domain.items():
        best = group[0]
        name = (best.get("title") or dom).split("|")[0].strip()[:120]
        url = best.get("url") or f"https://{dom}"
        snippets = hits_to_snippets(group)
        out.append((name, url, snippets))
    return out


def _few_shot_from_agdr(session: Session, limit: int = 5) -> str:
    from sqlalchemy import select

    from service_scout.db import AgentDecisionRecord

    rows = session.scalars(
        select(AgentDecisionRecord)
        .where(AgentDecisionRecord.verdict.in_(["accept", "reject"]))
        .order_by(AgentDecisionRecord.id.desc())
        .limit(limit)
    ).all()
    parts = []
    for r in rows:
        parts.append(f"- verdict={r.verdict} service={r.service_id} err={r.validation_error[:80]}")
    return "\n".join(parts)


def evaluate_candidate(
    session: Session,
    cfg: ScoutConfig,
    target: TargetConfig,
    governor: Governor,
    *,
    run_id: str,
    lane: str,
    name: str,
    url: str,
    snippets: list[str],
    known_sources: list[str],
    initial_queries: list[str],
    dry_run: bool,
) -> tuple[str, int]:
    """Return (notion_verdict_or_skip, tavily_credits_spent_in_this_candidate)."""
    credits_here = 0
    if is_force_rejected(url, cfg.overrides):
        forced = AgentVerdict(
            name=name,
            url=url,
            verdict="reject",
            confidence=5,
            uncertainty=1,
            reject_reason="force_reject_domain",
        )
        sid = resolve_service_id(session, name=name, url=url, overrides=cfg.overrides)
        persist_decision(
            session,
            cfg,
            target,
            run_id=run_id,
            service_id=sid,
            name=name,
            url=url,
            lane=lane,
            notion_verdict="reject",
            agent=forced,
            queries_run=initial_queries,
            tool_calls=[],
            constraints_checked=["force_reject_domain"],
            raw="{}",
            validation_error="",
            dry_run=dry_run,
        )
        return "reject", credits_here

    sid = resolve_service_id(session, name=name, url=url, overrides=cfg.overrides)
    existing = session.get(NotionLink, sid)
    if existing and existing.scout_verdict == "reject" and cfg.notion.on_revisit == "skip":
        log.info("skip_rejected service_id=%s", sid)
        return "skip", credits_here

    few = _few_shot_from_agdr(session)
    tool_calls: list[dict] = []
    queries_run = list(initial_queries)

    agent, raw, err = triage_with_retry(
        cfg.ollama,
        lane=lane,
        candidate_name=name,
        candidate_url=url,
        snippets=snippets,
        known_sources=known_sources,
        few_shot=few,
    )

    # Invalid output → reject invalid_agent_output
    if agent is None:
        persist_decision(
            session,
            cfg,
            target,
            run_id=run_id,
            service_id=sid,
            name=name,
            url=url,
            lane=lane,
            notion_verdict="reject",
            agent=AgentVerdict(
                name=name,
                url=url,
                verdict="reject",
                confidence=1,
                uncertainty=5,
                reject_reason="invalid_agent_output",
            ),
            queries_run=queries_run,
            tool_calls=tool_calls,
            constraints_checked=["schema_gate"],
            raw=raw,
            validation_error=err or "invalid_agent_output",
            dry_run=dry_run,
        )
        return "reject", credits_here

    esc = cfg.tavily.escalation
    rounds = 0
    # Escalation / branch
    need_escalate = agent.verdict == "need_more" or agent.confidence < cfg.governor.commit_threshold
    if need_escalate and governor.can_escalate() and rounds < cfg.governor.max_tool_rounds:
        if agent.uncertainty >= esc.min_uncertainty or agent.confidence < cfg.governor.commit_threshold:
            if esc.require_reason and agent.verdict == "need_more" and not agent.why_more_search:
                pass  # no escalate without reason for need_more
            else:
                qs = (agent.suggested_queries or [f"{name} free tier limits"])[
                    : esc.max_suggested_queries
                ]
                depth = (
                    "advanced"
                    if esc.allow_advanced_depth and cfg.tavily.search_depth == "advanced"
                    else "basic"
                )
                extra_hits: list[SearchHit] = []
                for q in qs[: esc.max_extra_per_candidate or 1]:
                    cost = credit_cost(depth)
                    if not governor.can_spend(cost):
                        break
                    try:
                        extra_hits.extend(
                            tavily_search(
                                api_key=cfg.tavily.api_key,
                                query=q,
                                max_results=cfg.tavily.max_results,
                                search_depth=depth,
                            )
                        )
                        governor.record_spend(cost, escalation=True)
                        credits_here += cost
                        tool_calls.append({"tool": "tavily_search", "query": q, "escalation": True})
                        queries_run.append(q)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("escalate_search_failed: %s", exc)
                if extra_hits:
                    snippets = snippets + hits_to_snippets(extra_hits)
                    agent2, raw2, err2 = triage_with_retry(
                        cfg.ollama,
                        lane=lane,
                        candidate_name=name,
                        candidate_url=url,
                        snippets=snippets,
                        known_sources=known_sources,
                        few_shot=few,
                    )
                    raw = raw2 or raw
                    err = err2 or err
                    if agent2 is not None:
                        agent = agent2
                    rounds += 1

    # Force decide if still need_more
    notion_verdict = apply_free_first_gates(agent, lane=lane)
    if agent.verdict == "need_more":
        notion_verdict = "needs_research"

    constraints = ["free_tier_exists", "scoring_hook_named", "schema_gate"]
    persist_decision(
        session,
        cfg,
        target,
        run_id=run_id,
        service_id=sid,
        name=agent.name or name,
        url=agent.url or url,
        lane=lane,
        notion_verdict=notion_verdict,
        agent=agent,
        queries_run=queries_run,
        tool_calls=tool_calls,
        constraints_checked=constraints,
        raw=raw,
        validation_error=err,
        dry_run=dry_run,
    )
    return notion_verdict, credits_here


def run_target_lane(
    session: Session,
    cfg: ScoutConfig,
    target: TargetConfig,
    lane: str,
    *,
    dry_run: bool = False,
) -> dict:
    run_id = uuid.uuid4().hex[:16]
    run = Run(run_id=run_id, lane=lane, target_id=target.id, status="running")
    session.add(run)
    session.commit()

    summary: dict = {
        "run_id": run_id,
        "lane": lane,
        "target": target.id,
        "blocked_reason": None,
        "partial_failures": [],
        "verdicts": [],
        "credits_spent": 0,
    }

    try:
        governor = Governor(cfg, session)
        registry = load_gap_registry(cfg, target)
        known = list(registry.get("known_sources") or [])
        lane_result = run_lane(lane, registry, cfg, governor)

        summary["blocked_reason"] = lane_result.get("blocked_reason")
        summary["partial_failures"] = lane_result.get("partial_failures")

        if lane_result.get("blocked_reason") and not lane_result.get("queries"):
            run.status = "blocked"
            run.detail = lane_result["blocked_reason"] or ""
            return summary

        if not governor.allow_lane_credits(lane_result.get("credits_reserved") or 0):
            # Still allow RSS-only infra (credits_reserved 0)
            if (lane_result.get("credits_reserved") or 0) > 0:
                run.status = "budget_blocked"
                summary["blocked_reason"] = "budget"
                return summary

        all_hits: list[SearchHit] = []
        queries_done: list[str] = []
        depth = (
            cfg.tavily.search_depth
            if cfg.tavily.search_depth in ("basic", "advanced")
            else "basic"
        )
        if cfg.tavily.escalation.allow_research_endpoint:
            log.warning("allow_research_endpoint ignored — not used")

        for q in lane_result.get("queries") or []:
            qtext = q["text"]
            source = q.get("source") or "gap_seed"
            if source == "rss":
                parts = qtext.rsplit(" ", 1)
                url = parts[-1] if parts and parts[-1].startswith("http") else ""
                title = qtext[:200]
                if url:
                    all_hits.append(SearchHit(title=title, url=url, content="rss"))
                queries_done.append(qtext)
                continue
            cost = credit_cost(depth)
            if not governor.can_spend(cost):
                log.info("stop_queries_budget")
                break
            try:
                hits = tavily_search(
                    api_key=cfg.tavily.api_key,
                    query=qtext,
                    max_results=cfg.tavily.max_results,
                    search_depth=depth,
                )
                governor.record_spend(cost)
                summary["credits_spent"] = int(summary.get("credits_spent") or 0) + cost
                all_hits.extend(hits)
                queries_done.append(qtext)
            except Exception as exc:  # noqa: BLE001
                log.warning("search_failed q=%s err=%s", qtext[:60], exc)

        clusters = _cluster_hits(all_hits, lane)
        for name, url, snippets in clusters[:8]:
            rejected = registry.get("rejected_research") or []
            if any(
                normalize_domain(r.get("url", "")) == normalize_domain(url) for r in rejected
            ):
                log.info("skip_known_rejected %s", url)
                continue
            v, esc_credits = evaluate_candidate(
                session,
                cfg,
                target,
                governor,
                run_id=run_id,
                lane=lane,
                name=name,
                url=url,
                snippets=snippets,
                known_sources=known,
                initial_queries=queries_done,
                dry_run=dry_run,
            )
            summary["credits_spent"] = int(summary.get("credits_spent") or 0) + esc_credits
            summary["verdicts"].append({"name": name, "url": url, "verdict": v})

        run.status = "ok"
        run.detail = f"verdicts={len(summary['verdicts'])}"
    except Exception as exc:  # noqa: BLE001 — mark run failed, continue other lanes
        log.exception("run_target_lane_failed lane=%s: %s", lane, exc)
        run.status = "error"
        run.detail = str(exc)[:500]
        summary["error"] = str(exc)
    finally:
        run.credits_spent = int(summary.get("credits_spent") or 0)
        run.finished_at = datetime.now(timezone.utc)
        session.commit()

    if run.status == "ok" and cfg.brain.enabled:
        brain_append(
            api_url=cfg.brain.api_url,
            token=cfg.brain.token,
            summary=(
                f"scout {target.id}/{lane}: {len(summary['verdicts'])} decisions, "
                f"credits={run.credits_spent}"
            ),
            project=target.id,
        )
    return summary


def run_all(
    session: Session,
    cfg: ScoutConfig,
    *,
    lanes: list[str] | None = None,
    target_id: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    results = []
    for target in cfg.targets:
        if target_id and target.id != target_id:
            continue
        use_lanes = lanes or target.lanes
        for lane in use_lanes:
            results.append(
                run_target_lane(session, cfg, target, lane, dry_run=dry_run)
            )
    return results
