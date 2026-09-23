"""Ollama OpenAI-compatible triage with Pydantic gate."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from service_scout.config import OllamaConfig
from service_scout.models import AgentVerdict, SearchHit

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Service Scout, an internal research judge for free-first tooling.
Return ONLY a single JSON object (no markdown) matching this schema:
{
  "name": "string",
  "url": "string",
  "verdict": "accept" | "reject" | "need_more",
  "uncertainty": 1-5,
  "confidence": 1-5,
  "why_more_search": "string or null",
  "suggested_queries": ["..."],
  "free_tier_summary": "string or null — numeric free limits when known",
  "scoring_or_infra_hook": "string or null — how this feeds composite scores or infra",
  "reject_reason": "string or null",
  "open_questions": ["..."]
}
Rules:
- accept ONLY if ALL are true:
  (1) machine-ingestible free path: public REST/GraphQL, free API key with limits, OR scrapable public JSON pattern;
  (2) clear scoring/infra hook named.
- A free *web terminal / screener / dashboard account* is NOT an API — reject with reject_reason=ui_only_no_api.
- Blogs, Substack, Medium, academy/guide/primer/tutorial essays are NOT data sources — reject with reject_reason=not_a_data_source (or content_only_no_api). Talking about FCF/cash flow does not make an article an API.
- Reject marketing pages for paid screeners that only sell a free guide.
- reject if paid-only, overlap with known sources, free tier too small, or no hook.
- need_more ONLY when an API/endpoint likely exists but free-tier numbers or auth details are missing; set why_more_search. Prefer reject over endless needs_research for content-only hits.
- Paraphrase; do not paste long copyrighted text.
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def ollama_triage(
    cfg: OllamaConfig,
    *,
    lane: str,
    candidate_name: str,
    candidate_url: str,
    snippets: list[str],
    known_sources: list[str],
    few_shot: str = "",
    temperature: float | None = None,
) -> tuple[AgentVerdict | None, str, str]:
    """
    Returns (verdict|None, raw_output, validation_error).
    """
    if not cfg.base_url or not cfg.model:
        raw = ""
        err = "ollama_not_configured"
        return None, raw, err

    user = {
        "lane": lane,
        "candidate": {"name": candidate_name, "url": candidate_url},
        "snippets": snippets[:12],
        "known_sources": known_sources[:40],
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT + (("\n\nExamples:\n" + few_shot) if few_shot else "")},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]
    base = cfg.base_url.rstrip("/")
    if not base.endswith("/v1"):
        # allow both .../v1 and root
        url = base + "/chat/completions" if base.endswith("/v1") else base + "/v1/chat/completions"
    else:
        url = base + "/chat/completions"

    headers = {"Content-Type": "application/json"}
    if cfg.api_token:
        headers["Authorization"] = f"Bearer {cfg.api_token}"

    temp = cfg.temperature if temperature is None else temperature
    payload = {
        "model": cfg.model,
        "temperature": temp,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    raw = ""
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        parsed = _extract_json(raw)
        # Ensure name/url defaults
        parsed.setdefault("name", candidate_name)
        parsed.setdefault("url", candidate_url)
        verdict = AgentVerdict.model_validate(parsed)
        return verdict, raw, ""
    except Exception as exc:  # noqa: BLE001
        log.warning("ollama_triage_failed: %s", exc)
        return None, raw or str(exc), str(exc)


def triage_with_retry(
    cfg: OllamaConfig,
    **kwargs: Any,
) -> tuple[AgentVerdict | None, str, str]:
    verdict, raw, err = ollama_triage(cfg, temperature=cfg.temperature, **kwargs)
    if verdict is not None:
        return verdict, raw, err
    if cfg.json_repair_retries < 1:
        return None, raw, err
    return ollama_triage(cfg, temperature=cfg.retry_temperature, **kwargs)


def hits_to_snippets(hits: list[SearchHit]) -> list[str]:
    out: list[str] = []
    for h in hits:
        out.append(f"{h.get('title','')} | {h.get('url','')} | {h.get('content','')[:400]}")
    return out
