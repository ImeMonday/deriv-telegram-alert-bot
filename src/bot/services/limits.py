from __future__ import annotations

import logging
from dataclasses import dataclass

LOG = logging.getLogger("bot.services.limits")

FREE_MAX_ACTIVE_ALERTS = 3
PREMIUM_MAX_ACTIVE_ALERTS = 100 


@dataclass(frozen=True)
class LimitResult:
    """Result of alert creation limit check"""
    allowed: bool
    reason: str


def can_create_alert(plan: str, active_alerts: int) -> LimitResult:
    """
    Check if user can create more alerts based on their plan.
    
    Args:
        plan: User's plan ("free" or "premium")
        active_alerts: Count of currently active alerts
    
    Returns:
        LimitResult with allowed (bool) and reason (str)
    """
    try:
        plan = (plan or "free").lower().strip()
        active_alerts = int(active_alerts)
        
        if plan == "premium":
            if active_alerts >= PREMIUM_MAX_ACTIVE_ALERTS:
                msg = f"Premium plan allows max {PREMIUM_MAX_ACTIVE_ALERTS} active alerts."
                LOG.debug("Premium user at limit: %d alerts", active_alerts)
                return LimitResult(False, msg)
            LOG.debug("Premium user can create alert: %d/%d", active_alerts, PREMIUM_MAX_ACTIVE_ALERTS)
            return LimitResult(True, "")

        
        if active_alerts >= FREE_MAX_ACTIVE_ALERTS:
            msg = f"Free plan allows max {FREE_MAX_ACTIVE_ALERTS} active alerts. Delete one or upgrade to premium."
            LOG.debug("Free user at limit: %d alerts", active_alerts)
            return LimitResult(False, msg)
        
        LOG.debug("Free user can create alert: %d/%d", active_alerts, FREE_MAX_ACTIVE_ALERTS)
        return LimitResult(True, "")
    
    except Exception as e:
        LOG.exception("Error checking alert limit: %s", e)
        
        return LimitResult(False, "Error checking alert limit. Please try again.")
