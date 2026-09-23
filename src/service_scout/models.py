"""Pydantic / TypedDict contracts for Scout."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator

AgentVerdictLiteral = Literal["accept", "reject", "need_more"]
ScoutNotionVerdict = Literal["accept", "reject", "needs_research"]


class AgentVerdict(BaseModel):
    """Structured Ollama output — validated before any tool spend."""

    name: str | None = None
    url: str | None = None
    verdict: AgentVerdictLiteral
    uncertainty: int = Field(ge=1, le=5, default=3)
    confidence: int = Field(ge=1, le=5, default=3)
    why_more_search: str | None = None
    suggested_queries: list[str] = Field(default_factory=list)
    free_tier_summary: str | None = None
    scoring_or_infra_hook: str | None = None
    reject_reason: str | None = None
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("suggested_queries", mode="before")
    @classmethod
    def _coerce_queries(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v)

    @field_validator("open_questions", mode="before")
    @classmethod
    def _coerce_questions(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return list(v)


class Query(TypedDict):
    text: str
    lane: str
    gap_id: NotRequired[str | None]
    source: NotRequired[str]  # gap_seed | rss | override | escalate


class LaneResult(TypedDict):
    queries: list[Query]
    credits_reserved: int
    blocked_reason: str | None
    partial_failures: list[str]


class SearchHit(TypedDict):
    title: str
    url: str
    content: str
    score: NotRequired[float]


class Candidate(BaseModel):
    """A service under evaluation."""

    name: str
    url: str
    lane: str
    snippets: list[str] = Field(default_factory=list)
    service_id: str | None = None
    gap_ids: list[str] = Field(default_factory=list)
