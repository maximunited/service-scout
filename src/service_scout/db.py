"""SQLAlchemy ops store — Postgres preferred, SQLite fallback."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    DateTime,
    Integer,
    MetaData,
    String,
    Text,
    create_engine,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from service_scout.config import DatabaseConfig


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData()


class UsageMonthly(Base):
    __tablename__ = "usage_monthly"

    year_month: Mapped[str] = mapped_column(String(7), primary_key=True)
    tavily_credits: Mapped[int] = mapped_column(Integer, default=0)
    escalations: Mapped[int] = mapped_column(Integer, default=0)


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lane: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="running")
    credits_spent: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")


class ServiceAlias(Base):
    __tablename__ = "service_aliases"

    service_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(512), default="")
    domains: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AgentDecisionRecord(Base):
    __tablename__ = "agent_decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    service_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    candidate_fingerprint: Mapped[str] = mapped_column(String(512), default="")
    verdict: Mapped[str] = mapped_column(String(32), default="")
    queries_run: Mapped[str] = mapped_column(Text, default="[]")
    tool_calls: Mapped[str] = mapped_column(Text, default="[]")
    constraints_checked: Mapped[str] = mapped_column(Text, default="[]")
    raw_agent_output: Mapped[str] = mapped_column(Text, default="")
    validation_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class DigestQueueItem(Base):
    __tablename__ = "digest_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(512), default="")
    scout_verdict: Mapped[str] = mapped_column(String(32), default="")
    notion_page_id: Mapped[str] = mapped_column(String(64), default="")
    url: Mapped[str] = mapped_column(String(1024), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    flushed: Mapped[int] = mapped_column(Integer, default=0)


class NotionLink(Base):
    __tablename__ = "notion_links"

    service_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    notion_page_id: Mapped[str] = mapped_column(String(64), default="")
    scout_verdict: Mapped[str] = mapped_column(String(32), default="")
    last_updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def make_engine(db: DatabaseConfig) -> Engine:
    if db.url:
        url = db.url
        if url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return create_engine(url, pool_pre_ping=True)
    path = Path(db.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}", future=True)


def init_db(engine: Engine) -> sessionmaker[Session]:
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def year_month_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_or_create_usage(session: Session, ym: str | None = None) -> UsageMonthly:
    ym = ym or year_month_now()
    row = session.get(UsageMonthly, ym)
    if row is None:
        row = UsageMonthly(year_month=ym, tavily_credits=0, escalations=0)
        session.add(row)
        session.commit()
    return row


def domains_list(alias: ServiceAlias) -> list[str]:
    try:
        return list(json.loads(alias.domains or "[]"))
    except json.JSONDecodeError:
        return []


def set_domains(alias: ServiceAlias, domains: list[str]) -> None:
    alias.domains = json.dumps(sorted(set(domains)))


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
