"""
ocr_runner.py — Phase 2: OCR-based UI automation.

Pipeline:
    1. Take screenshot
    2. [OPTIONAL] Run profile analyser → decide connect/skip before clicking
    3. Run OCR → extract cleaned words with confidence filtering
    4. Skip any words matching skip_keywords
    5. Match target keywords from task config
    6. Click on the center of matched word bounding boxes
    7. Loop N times
"""

import logging
import time
from typing import Any, Dict, List, Optional, Set

import pyautogui

from autopilot.actions.coordinate_runner import load_task_config
from autopilot.utils.ocr_utils import OCRWord, extract_words, find_keyword
from autopilot.utils.screenshot import take_screenshot

logger = logging.getLogger(__name__)

# Structured response type
ActionResult = Dict[str, Any]


def _build_result(
    success: bool,
    action_taken: str,
    phase_used: int = 2,
    coords: Optional[Dict[str, int]] = None,
    error: Optional[str] = None,
    analyser: Optional[Dict[str, Any]] = None,
) -> ActionResult:
    """Build a standardized action result dict."""
    result = {
        "success": success,
        "action_taken": action_taken,
        "coords": coords,
        "phase_used": phase_used,
        "error": error,
    }
    if analyser:
        result["analyser"] = analyser
    return result


def run_ocr_sequence(
    task_name: str,
    dry_run: bool = False,
    max_retries: int = 3,
    loop: Optional[int] = None,
    delay_ms: Optional[int] = None,
    analyse: bool = False,
    analyser_overrides: Optional[Dict[str, Any]] = None,
) -> List[ActionResult]:
    """
    Execute an OCR-based click sequence from a task config.

    For each loop iteration, processes each keyword target:
        1. Take a fresh screenshot
        2. [If analyse=True] Run profile analyser → skip if filters fail
        3. Run OCR pipeline with confidence filtering
        4. Skip words matching skip_keywords
        5. Find the keyword in OCR results
        6. Click the center of the matched bounding box

    Args:
        task_name: Name of the task config to load.
        dry_run: If True, log actions without actually clicking.
        max_retries: Number of OCR retry attempts per keyword if not found.
        loop: Number of loop iterations. Overrides config value.
        delay_ms: Delay between clicks in ms. Overrides config value.
        analyse: If True, run profile analyser before each click decision.
        analyser_overrides: CLI overrides for analyser filters (gender, age, followers).

    Returns:
        List of ActionResult dicts — one per keyword target across all loops.
    """
    config = load_task_config(task_name)

    # Read from phase2 section (new format) or fall back to old format
    phase2 = config.get("phase2", {})
    defaults = config.get("defaults", {})

    # Keywords to click
    keywords: List[str] = phase2.get("keywords", [])
    if not keywords:
        # Fall back to old ocr_targets format
        old_targets = config.get("ocr_targets", [])
        old_targets = sorted(old_targets, key=lambda t: t.get("priority", 999))
        keywords = [t["keyword"] for t in old_targets]

    # Keywords to skip (new feature)
    skip_keywords: Set[str] = set(
        k.strip().lower() for k in phase2.get("skip_keywords", [])
    )

    confidence_threshold = phase2.get(
        "confidence_threshold",
        defaults.get("ocr_confidence_threshold", 60),
    )
    config_delay_ms = phase2.get("delay_ms", 1200)
    config_loop = phase2.get("loop", 10)
    config_retries = defaults.get("max_retries", max_retries)
    screenshot_region = defaults.get("screenshot_region")

    # CLI overrides > config values
    actual_loop = loop if loop is not None else config_loop
    actual_delay = (delay_ms if delay_ms is not None else config_delay_ms) / 1000.0

    # ── Analyser setup ──
    analyser_config = config.get("analyser", {})
    # Enable via CLI flag or YAML config
    analyser_enabled = analyse or analyser_config.get("enabled", False)

    # Apply CLI overrides to analyser config
    if analyser_overrides and analyser_enabled:
        analyser_config = _apply_analyser_overrides(analyser_config, analyser_overrides)

    results: List[ActionResult] = []

    # Analyser stats
    analysed_count = 0
    skipped_by_filter = 0
    connected_count = 0

    logger.info(
        "Starting OCR sequence — task=%s, keywords=%s, skip=%s, loop=%d, "
        "threshold=%d, delay=%.1fs, dry_run=%s, analyser=%s",
        task_name,
        keywords,
        skip_keywords,
        actual_loop,
        confidence_threshold,
        actual_delay,
        dry_run,
        analyser_enabled,
    )

    for iteration in range(1, actual_loop + 1):
        logger.info("── Loop %d/%d ──", iteration, actual_loop)

        # ── Run profile analyser before clicking ──
        analyser_result = None
        if analyser_enabled:
            analyser_result = _run_analyser(analyser_config, dry_run)
            analysed_count += 1

            if analyser_result and analyser_result.get("action") == "skip":
                skipped_by_filter += 1
                logger.info(
                    "⏭ Analyser: SKIP — %s (gender=%s, age=%d, followers=%d)",
                    analyser_result.get("reason", "filter failed"),
                    analyser_result.get("gender", "?"),
                    analyser_result.get("age", 0),
                    analyser_result.get("followers", 0),
                )
                results.append(
                    _build_result(
                        success=True,
                        action_taken=f"analyser_skip: {analyser_result.get('reason', '')}",
                        phase_used=6,
                        analyser=analyser_result,
                    )
                )
                # Scroll to next profile (simulate)
                if not dry_run:
                    _scroll_to_next()
                time.sleep(actual_delay)
                continue

            elif analyser_result and analyser_result.get("action") == "flag":
                logger.info(
                    "⚠ Analyser: FLAG — %s (proceeding with caution)",
                    analyser_result.get("reason", ""),
                )

            elif analyser_result and analyser_result.get("action") == "connect":
                connected_count += 1
                logger.info(
                    "✅ Analyser: CONNECT — gender=%s, age=%d, followers=%d",
                    analyser_result.get("gender", "?"),
                    analyser_result.get("age", 0),
                    analyser_result.get("followers", 0),
                )

        for keyword in keywords:
            # Check if this keyword should be skipped
            if keyword.strip().lower() in skip_keywords:
                logger.info("Skipping keyword '%s' (in skip_keywords list)", keyword)
                results.append(
                    _build_result(
                        success=True,
                        action_taken=f"skipped {keyword}",
                        analyser=analyser_result,
                    )
                )
                continue

            result = _process_ocr_target(
                keyword=keyword,
                confidence_threshold=confidence_threshold,
                click_delay=actual_delay,
                max_retries=config_retries,
                screenshot_region=screenshot_region,
                skip_keywords=skip_keywords,
                dry_run=dry_run,
            )

            # Attach analyser result to the action result
            if analyser_result:
                result["analyser"] = analyser_result

            results.append(result)

            # If a target fails, stop this iteration
            if not result["success"]:
                logger.warning(
                    "Stopping iteration %d — keyword '%s' not found after retries",
                    iteration,
                    keyword,
                )
                break

    logger.info(
        "OCR sequence complete — %d/%d succeeded | Analysed: %d | Skipped(filter): %d | Connected: %d",
        sum(1 for r in results if r["success"]),
        len(results),
        analysed_count,
        skipped_by_filter,
        connected_count,
    )
    return results


def _apply_analyser_overrides(
    config: Dict[str, Any],
    overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Apply CLI overrides to the analyser config.

    Supported overrides:
        gender, age_min, age_max, followers_min, followers_max, model

    Args:
        config: Original analyser config from YAML.
        overrides: CLI override values.

    Returns:
        Modified config dict.
    """
    import copy
    cfg = copy.deepcopy(config)
    filters = cfg.setdefault("filters", {})

    # Gender override
    if "gender" in overrides and overrides["gender"]:
        gender_val = overrides["gender"].lower()
        if gender_val == "any":
            filters.setdefault("gender", {})["allow"] = ["any"]
        else:
            filters.setdefault("gender", {})["allow"] = [gender_val]

    # Age overrides
    if "age_min" in overrides and overrides["age_min"] is not None:
        filters.setdefault("age", {})["min"] = overrides["age_min"]
    if "age_max" in overrides and overrides["age_max"] is not None:
        filters.setdefault("age", {})["max"] = overrides["age_max"]

    # Follower overrides
    if "followers_min" in overrides and overrides["followers_min"] is not None:
        filters.setdefault("followers", {})["min"] = overrides["followers_min"]
    if "followers_max" in overrides and overrides["followers_max"] is not None:
        filters.setdefault("followers", {})["max"] = overrides["followers_max"]

    # Model override
    if "model" in overrides and overrides["model"]:
        cfg["model"] = overrides["model"]

    return cfg


def _run_analyser(
    analyser_config: Dict[str, Any],
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Run the profile analyser pipeline.

    Returns the analyser result dict, or None if analysis fails entirely.
    Never crashes — returns a skip result on error.
    """
    try:
        from autopilot.analyser.profile_analyser import analyse_profile

        result = analyse_profile(
            analyser_config=analyser_config,
            dry_run=dry_run,
        )
        return result

    except Exception as exc:
        logger.error("Analyser pipeline error: %s", exc)
        return {
            "gender": "unknown",
            "age": 0,
            "confidence": 0.0,
            "followers": 0,
            "action": "skip",
            "reason": f"analyser error: {exc}",
            "phase_used": 6,
            "success": False,
            "error": str(exc),
        }


def _scroll_to_next() -> None:
    """Scroll down to the next profile card."""
    try:
        pyautogui.scroll(-3)  # Scroll down
        time.sleep(0.5)
    except Exception as exc:
        logger.warning("Scroll failed: %s", exc)


def _process_ocr_target(
    keyword: str,
    confidence_threshold: int,
    click_delay: float,
    max_retries: int,
    screenshot_region: Optional[Any],
    skip_keywords: Optional[Set[str]] = None,
    dry_run: bool = False,
) -> ActionResult:
    """
    Try to find and click a single OCR keyword target.

    Retries up to max_retries times with fresh screenshots each attempt.
    Filters out any words matching skip_keywords before matching.

    Args:
        keyword: Target text to find via OCR.
        confidence_threshold: OCR confidence filter.
        click_delay: Delay after clicking (seconds).
        max_retries: Maximum retry attempts.
        screenshot_region: Optional (left, top, width, height) tuple.
        skip_keywords: Set of keywords to ignore in OCR results.
        dry_run: If True, don't actually click.

    Returns:
        ActionResult dict.
    """
    region_tuple = tuple(screenshot_region) if screenshot_region else None
    skip_set = skip_keywords or set()

    for attempt in range(1, max_retries + 1):
        logger.info(
            "OCR attempt %d/%d — looking for '%s'",
            attempt,
            max_retries,
            keyword,
        )

        try:
            screenshot = take_screenshot(region=region_tuple)
            words = extract_words(screenshot, confidence_threshold=confidence_threshold)

            # Filter out skip_keywords from results
            if skip_set:
                filtered_words = [
                    w for w in words if w.text not in skip_set
                ]
                skipped_count = len(words) - len(filtered_words)
                if skipped_count > 0:
                    logger.debug(
                        "Filtered %d words matching skip_keywords", skipped_count
                    )
                words = filtered_words

            match: Optional[OCRWord] = find_keyword(words, keyword)

            if match:
                cx, cy = match.center

                if dry_run:
                    logger.info(
                        "[DRY RUN] Would click '%s' at (%d, %d)", keyword, cx, cy
                    )
                else:
                    logger.info("Clicking '%s' at (%d, %d)", keyword, cx, cy)
                    pyautogui.click(cx, cy)

                time.sleep(click_delay)

                return _build_result(
                    success=True,
                    action_taken=f"clicked {keyword} at ({cx}, {cy})",
                    coords={"x": cx, "y": cy},
                )

            # Not found — retry after a short pause
            logger.debug("Keyword '%s' not found — retrying in 0.5s", keyword)
            time.sleep(0.5)

        except Exception as exc:
            logger.error("OCR attempt %d failed for '%s': %s", attempt, keyword, exc)
            time.sleep(0.5)

    # All retries exhausted
    return _build_result(
        success=False,
        action_taken=f"ocr_click_{keyword}",
        error=f"Keyword '{keyword}' not found after {max_retries} attempts",
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    # Run LinkedIn connect task in dry-run mode by default
    results = run_ocr_sequence("linkedin_connect", dry_run=True, loop=1)
    for r in results:
        print(r)
