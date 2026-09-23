"""Credit / escalation governor — external controller over the agent."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from service_scout.config import ScoutConfig
from service_scout.db import get_or_create_usage, year_month_now


@dataclass
class BudgetSnapshot:
    year_month: str
    tavily_used: int
    escalations_used: int
    tavily_remaining: int
    escalation_remaining: int
    hard_cap: int


class Governor:
    def __init__(self, cfg: ScoutConfig, session: Session) -> None:
        self.cfg = cfg
        self.session = session

    def snapshot(self) -> BudgetSnapshot:
        usage = get_or_create_usage(self.session)
        # Soft reserve for Cursor/MCP — scout refuses to spend into that headroom
        # against a notional free-tier ceiling of 1000 credits.
        notional_free = 1000
        soft_ceiling = max(
            0,
            min(
                self.cfg.tavily.monthly_credit_budget,
                notional_free - self.cfg.tavily.reserved_for_cursor_mcp,
            ),
        )
        hard_cap = soft_ceiling if soft_ceiling > 0 else self.cfg.tavily.monthly_credit_budget
        return BudgetSnapshot(
            year_month=usage.year_month,
            tavily_used=usage.tavily_credits,
            escalations_used=usage.escalations,
            tavily_remaining=max(0, hard_cap - usage.tavily_credits),
            escalation_remaining=max(
                0,
                self.cfg.tavily.escalation.monthly_extra_searches - usage.escalations,
            ),
            hard_cap=hard_cap,
        )

    def can_spend(self, credits: int = 1) -> bool:
        return self.snapshot().tavily_remaining >= credits

    def can_escalate(self) -> bool:
        esc = self.cfg.tavily.escalation
        if not esc.enabled:
            return False
        snap = self.snapshot()
        return snap.escalation_remaining > 0 and snap.tavily_remaining > 0

    def record_spend(self, credits: int = 1, *, escalation: bool = False) -> None:
        usage = get_or_create_usage(self.session)
        usage.tavily_credits += credits
        if escalation:
            usage.escalations += 1
        self.session.commit()

    def allow_lane_credits(self, reserved: int) -> bool:
        return self.can_spend(max(1, reserved)) if reserved else True
