"""
vision_runner.py — Phase 3: Vision AI-based UI automation.

Pipeline:
    1. Take screenshot
    2. Send to Claude Vision API with target description
    3. Parse returned JSON {x, y} coordinates
    4. Click at the coordinates
    5. Falls back to OCR runner (Phase 2) if vision fails
    6. Loop N times
"""

import logging
import time
from typing import Any, Dict, List, Optional, Set

import pyautogui

from autopilot.actions.coordinate_runner import load_task_config
from autopilot.actions.ocr_runner import _process_ocr_target
from autopilot.utils.screenshot import take_screenshot
from autopilot.utils.vision_utils import ask_vision_for_coords

logger = logging.getLogger(__name__)

# Structured response type
ActionResult = Dict[str, Any]


def _build_result(
    success: bool,
    action_taken: str,
    phase_used: int = 3,
    coords: Optional[Dict[str, int]] = None,
    error: Optional[str] = None,
) -> ActionResult:
    """Build a standardized action result dict."""
    return {
        "success": success,
        "action_taken": action_taken,
        "coords": coords,
        "phase_used": phase_used,
        "error": error,
    }


def run_vision_sequence(
    task_name: str,
    dry_run: bool = False,
    fallback_to_ocr: bool = True,
    loop: Optional[int] = None,
    delay_ms: Optional[int] = None,
) -> List[ActionResult]:
    """
    Execute a Vision AI-based click sequence from a task config.

    For each loop iteration, processes each keyword target:
        1. Take a screenshot
        2. Ask Claude Vision for coordinates of the target
        3. Click at the returned coordinates
        4. If vision fails, optionally fall back to OCR (Phase 2)

    Args:
        task_name: Name of the task config to load.
        dry_run: If True, log actions without actually clicking.
        fallback_to_ocr: If True, fall back to OCR when vision fails.
        loop: Number of loop iterations. Overrides config value.
        delay_ms: Delay between clicks in ms. Overrides config value.

    Returns:
        List of ActionResult dicts — one per target across all loops.
    """
    config = load_task_config(task_name)

    # Read from phase3 and phase2 sections
    phase3 = config.get("phase3", {})
    phase2 = config.get("phase2", {})
    defaults = config.get("defaults", {})

    # Get target prompt and keywords
    target_prompt = phase3.get("target_prompt", "Connect button")

    # Keywords come from phase2 for the fallback and target list
    keywords: List[str] = phase2.get("keywords", [])
    if not keywords:
        old_targets = config.get("ocr_targets", [])
        old_targets = sorted(old_targets, key=lambda t: t.get("priority", 999))
        keywords = [t["keyword"] for t in old_targets]

    skip_keywords: Set[str] = set(
        k.strip().lower() for k in phase2.get("skip_keywords", [])
    )

    confidence_threshold = phase2.get(
        "confidence_threshold",
        defaults.get("ocr_confidence_threshold", 60),
    )
    max_retries = defaults.get("max_retries", 3)
    screenshot_region = defaults.get("screenshot_region")

    config_delay_ms = phase3.get("delay_ms", 1200)
    config_loop = phase3.get("loop", 10)

    # CLI overrides > config
    actual_loop = loop if loop is not None else config_loop
    actual_delay = (delay_ms if delay_ms is not None else config_delay_ms) / 1000.0

    results: List[ActionResult] = []

    logger.info(
        "Starting vision sequence — task=%s, keywords=%s, loop=%d, "
        "fallback_to_ocr=%s, delay=%.1fs, dry_run=%s",
        task_name,
        keywords,
        actual_loop,
        fallback_to_ocr,
        actual_delay,
        dry_run,
    )

    for iteration in range(1, actual_loop + 1):
        logger.info("── Loop %d/%d ──", iteration, actual_loop)

        for keyword in keywords:
            if keyword.strip().lower() in skip_keywords:
                logger.info("Skipping keyword '%s' (in skip_keywords list)", keyword)
                continue

            description = f"'{keyword}' button — {target_prompt}"

            # Try Vision AI first
            result = _try_vision_click(
                keyword=keyword,
                description=description,
                click_delay=actual_delay,
                screenshot_region=screenshot_region,
                dry_run=dry_run,
            )

            if result["success"]:
                results.append(result)
                continue

            # Vision failed — try OCR fallback
            if fallback_to_ocr:
                logger.info(
                    "Vision failed for '%s' — falling back to OCR", keyword
                )
                ocr_result = _process_ocr_target(
                    keyword=keyword,
                    confidence_threshold=confidence_threshold,
                    click_delay=actual_delay,
                    max_retries=max_retries,
                    screenshot_region=screenshot_region,
                    skip_keywords=skip_keywords,
                    dry_run=dry_run,
                )
                # Mark that fallback was used
                ocr_result["action_taken"] = f"vision→ocr fallback: {keyword}"
                ocr_result["phase_used"] = 2
                results.append(ocr_result)

                if not ocr_result["success"]:
                    logger.warning(
                        "Both vision and OCR failed for '%s' — stopping iteration",
                        keyword,
                    )
                    break
            else:
                results.append(result)
                logger.warning(
                    "Vision failed for '%s' and no fallback — stopping", keyword
                )
                break

    logger.info(
        "Vision sequence complete — %d/%d succeeded",
        sum(1 for r in results if r["success"]),
        len(results),
    )
    return results


def _try_vision_click(
    keyword: str,
    description: str,
    click_delay: float,
    screenshot_region: Optional[Any],
    dry_run: bool,
) -> ActionResult:
    """
    Attempt to find and click a target using Claude Vision.

    Args:
        keyword: Target keyword (used for action naming).
        description: Human-readable description for the vision prompt.
        click_delay: Delay after clicking.
        screenshot_region: Optional screenshot region.
        dry_run: If True, don't actually click.

    Returns:
        ActionResult dict.
    """
    try:
        region_tuple = tuple(screenshot_region) if screenshot_region else None
        screenshot = take_screenshot(region=region_tuple)

        coords = ask_vision_for_coords(screenshot, description)

        if coords is None:
            return _build_result(
                success=False,
                action_taken=f"vision_click_{keyword}",
                error=f"Vision API could not locate '{description}'",
            )

        x, y = coords

        if dry_run:
            logger.info("[DRY RUN] Would click '%s' at (%d, %d)", keyword, x, y)
        else:
            logger.info("Vision click '%s' at (%d, %d)", keyword, x, y)
            pyautogui.click(x, y)

        time.sleep(click_delay)

        return _build_result(
            success=True,
            action_taken=f"clicked {keyword} at ({x}, {y})",
            coords={"x": x, "y": y},
        )

    except Exception as exc:
        logger.error("Vision click failed for '%s': %s", keyword, exc)
        return _build_result(
            success=False,
            action_taken=f"vision_click_{keyword}",
            error=str(exc),
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    results = run_vision_sequence("linkedin_connect", dry_run=True, loop=1)
    for r in results:
        print(r)
