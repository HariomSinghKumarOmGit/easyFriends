"""
profile_analyser.py — Orchestrates the full profile analysis pipeline.

Pipeline:
    1. Take screenshot
    2. Crop profile photo region → gender_age.analyse()
    3. Crop follower text region → follower_parser.parse()
    4. Feed all results to decision_engine.decide()
    5. Return structured AnalyserResult

Runs 100% locally. No cloud API keys needed.
"""

import logging
from typing import Any, Dict, Optional

from PIL import Image

from autopilot.analyser.decision_engine import decide
from autopilot.analyser.follower_parser import parse_follower_count
from autopilot.analyser.gender_age import analyse as analyse_gender_age
from autopilot.utils.crop_utils import crop_from_screenshot
from autopilot.utils.screenshot import take_screenshot

logger = logging.getLogger(__name__)

# Structured analyser response
AnalyserResult = Dict[str, Any]


def analyse_profile(
    screenshot: Optional[Image.Image] = None,
    analyser_config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> AnalyserResult:
    """
    Run the full profile analysis pipeline on the current screen.

    Steps:
        1. Grab screenshot (or use provided one)
        2. Crop profile photo → run gender/age model
        3. Crop follower region → OCR → parse count
        4. Apply filter rules → connect / skip / flag

    Args:
        screenshot: Optional pre-captured screenshot. Takes a new one if None.
        analyser_config: Analyser section from YAML config.
        dry_run: If True, analysis still runs but no action is taken.

    Returns:
        AnalyserResult dict with gender, age, confidence, followers,
        action, reason, and any errors.
    """
    config = analyser_config or {}

    # Default result
    result: AnalyserResult = {
        "gender": "unknown",
        "age": 0,
        "confidence": 0.0,
        "followers": 0,
        "action": "skip",
        "reason": "analysis not completed",
        "phase_used": 6,
        "success": False,
        "error": None,
    }

    # ── Step 1: Screenshot ──
    if screenshot is None:
        try:
            screenshot = take_screenshot()
        except Exception as exc:
            result["error"] = f"Screenshot failed: {exc}"
            logger.error(result["error"])
            return result

    # ── Step 2: Crop regions ──
    photo_region = config.get("photo_crop", {
        "x": 80, "y": 150, "width": 120, "height": 120,
    })
    follower_region = config.get("follower_crop", {
        "x": 80, "y": 290, "width": 400, "height": 40,
    })

    photo_crop, follower_crop = crop_from_screenshot(
        screenshot,
        photo_region=photo_region,
        follower_region=follower_region,
    )

    # ── Step 3: Gender/Age analysis ──
    model = config.get("model", "deepface")
    llava_endpoint = config.get("llava_endpoint", "http://localhost:11434/api/generate")
    llava_model = config.get("llava_model", "llava")
    min_confidence = config.get("filters", {}).get("gender", {}).get("min_confidence", 0.65)

    if photo_crop:
        ga_result = analyse_gender_age(
            image=photo_crop,
            model=model,
            llava_endpoint=llava_endpoint,
            llava_model=llava_model,
            min_confidence=min_confidence,
        )
        result["gender"] = ga_result["gender"]
        result["age"] = ga_result["age"]
        result["confidence"] = ga_result["confidence"]

        if ga_result.get("error"):
            logger.warning("Gender/age analysis warning: %s", ga_result["error"])
    else:
        logger.warning("No profile photo crop — skipping gender/age analysis")
        result["gender"] = "unknown"

    # ── Step 4: Follower count ──
    if follower_crop:
        follower_result = parse_follower_count(follower_crop)
        result["followers"] = follower_result["count"]

        if follower_result.get("error"):
            logger.warning("Follower parsing warning: %s", follower_result["error"])
    else:
        logger.warning("No follower crop — skipping follower count")

    # ── Step 5: Decision ──
    filters = config.get("filters", {})
    decision = decide(
        gender=result["gender"],
        age=result["age"],
        confidence=result["confidence"],
        followers=result["followers"],
        filters=filters,
    )

    result["action"] = decision["action"]
    result["reason"] = decision["reason"]
    result["success"] = True  # Analysis itself succeeded

    logger.info(
        "Profile analysis complete — gender=%s age=%d followers=%d → %s (%s)",
        result["gender"],
        result["age"],
        result["followers"],
        result["action"],
        result["reason"],
    )

    return result


def should_connect(result: AnalyserResult) -> bool:
    """
    Quick check: does the analysis say we should connect?

    Args:
        result: AnalyserResult from analyse_profile().

    Returns:
        True if action is 'connect' or 'flag' (flag = proceed with caution).
    """
    return result.get("action") in ("connect", "flag")
