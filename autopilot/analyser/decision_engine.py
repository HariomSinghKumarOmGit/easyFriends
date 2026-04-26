"""
decision_engine.py — Apply configurable filter rules to decide: connect / skip / flag.

Reads filter rules from the analyser YAML config and evaluates the
profile analysis results against them.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Decision result type
DecisionResult = Dict[str, Any]

# Valid actions
ACTION_CONNECT = "connect"
ACTION_SKIP = "skip"
ACTION_FLAG = "flag"


def decide(
    gender: str,
    age: int,
    confidence: float,
    followers: int,
    filters: Dict[str, Any],
) -> DecisionResult:
    """
    Apply filter rules to a profile analysis and return a connect/skip/flag decision.

    Filter rules (from YAML):
        gender.allow: ["female"] | ["male"] | ["any"] | ["male", "female"]
        gender.min_confidence: 0.65
        age.min: 20
        age.max: 40
        followers.min: 500
        followers.max: 50000

    Args:
        gender: Detected gender ("male", "female", "unknown").
        age: Estimated age (integer).
        confidence: Gender detection confidence (0.0 - 1.0).
        followers: Follower/connection count.
        filters: Filter rules dict from YAML config.

    Returns:
        DecisionResult with action (connect/skip/flag) and reason.
    """
    reasons: List[str] = []

    # ── Gender filter ──
    gender_filter = filters.get("gender", {})
    allowed_genders = gender_filter.get("allow", ["any"])
    min_confidence = gender_filter.get("min_confidence", 0.5)

    if "any" not in allowed_genders:
        if gender == "unknown":
            reasons.append(f"gender unknown (confidence={confidence:.2f})")
        elif gender not in allowed_genders:
            return _decision(
                ACTION_SKIP,
                f"gender '{gender}' not in allowed list {allowed_genders}",
            )

        # Check confidence threshold
        if confidence < min_confidence and gender != "unknown":
            reasons.append(
                f"gender confidence {confidence:.2f} < threshold {min_confidence}"
            )

    # ── Age filter ──
    age_filter = filters.get("age", {})
    age_min = age_filter.get("min", 0)
    age_max = age_filter.get("max", 999)

    if age > 0:  # Only filter if age was detected
        if age < age_min:
            return _decision(
                ACTION_SKIP,
                f"age {age} < minimum {age_min}",
            )
        if age > age_max:
            return _decision(
                ACTION_SKIP,
                f"age {age} > maximum {age_max}",
            )

    # ── Follower filter ──
    follower_filter = filters.get("followers", {})
    follower_min = follower_filter.get("min", 0)
    follower_max = follower_filter.get("max", 999_999_999)

    if followers > 0:  # Only filter if count was parsed
        if followers < follower_min:
            return _decision(
                ACTION_SKIP,
                f"followers {followers:,} < minimum {follower_min:,}",
            )
        if followers > follower_max:
            return _decision(
                ACTION_SKIP,
                f"followers {followers:,} > maximum {follower_max:,} (likely brand/fake)",
            )

    # ── All filters passed ──
    if reasons:
        # Had warnings but nothing hard-failed — flag for review
        return _decision(
            ACTION_FLAG,
            "soft warnings: " + "; ".join(reasons),
        )

    return _decision(ACTION_CONNECT, "all filters passed")


def _decision(action: str, reason: str) -> DecisionResult:
    """Build a decision result dict."""
    logger.info("Decision: %s — %s", action.upper(), reason)
    return {
        "action": action,
        "reason": reason,
    }
