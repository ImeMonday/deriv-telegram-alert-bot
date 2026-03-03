from __future__ import annotations

from dataclasses import dataclass

FREE_MAX_ACTIVE_ALERTS = 3


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    reason: str


def can_create_alert(plan: str, active_alerts: int) -> LimitResult:
    plan = (plan or "free").lower()
    if plan == "premium":
        return LimitResult(True, "")

    if active_alerts >= FREE_MAX_ACTIVE_ALERTS:
        return LimitResult(
            False,
            f"Free plan allows max {FREE_MAX_ACTIVE_ALERTS} active alerts. Delete one or upgrade.",
        )

    return LimitResult(True, "")