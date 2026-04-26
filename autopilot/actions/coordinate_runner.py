"""
coordinate_runner.py — Phase 1: Coordinate-based UI automation.

Reads a task config (YAML) and executes a sequence of hardcoded (x, y) clicks
with configurable delays and loop count. No screen reading — purely positional.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyautogui
import yaml

logger = logging.getLogger(__name__)

# Structured response type
ActionResult = Dict[str, Any]


def _build_result(
    success: bool,
    action_taken: str,
    phase_used: int = 1,
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


def load_task_config(task_name: str) -> Dict[str, Any]:
    """
    Load a task YAML config from config/tasks/<task_name>.yaml.

    Args:
        task_name: Name of the task file (without extension).

    Returns:
        Parsed YAML as a dict.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
    """
    config_dir = Path(__file__).resolve().parent.parent / "config" / "tasks"
    config_path = config_dir / f"{task_name}.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Task config not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    logger.info("Loaded task config: %s", config_path)
    return config


def run_coordinate_sequence(
    task_name: str,
    dry_run: bool = False,
    loop: Optional[int] = None,
    delay_ms: Optional[int] = None,
) -> List[ActionResult]:
    """
    Execute a coordinate-based click sequence from a task config.

    Reads phase1.coordinates from the YAML config and clicks each (x, y)
    in order, repeating for `loop` iterations with the specified delay.

    Args:
        task_name: Name of the task config to load.
        dry_run: If True, log actions without actually clicking.
        loop: Number of loop iterations. Overrides config value.
        delay_ms: Delay between clicks in milliseconds. Overrides config value.

    Returns:
        List of ActionResult dicts — one per click action across all loops.
    """
    config = load_task_config(task_name)

    # Read from phase1 section (new format) or fall back to old format
    phase1 = config.get("phase1", {})
    coordinates = phase1.get("coordinates", [])

    # Fall back to old format if phase1 section is missing
    if not coordinates:
        old_actions = config.get("coordinate_actions", [])
        coordinates = [
            {"x": a["x"], "y": a["y"], "label": a.get("name", a.get("description", "unnamed"))}
            for a in old_actions
        ]

    config_delay_ms = phase1.get("delay_ms", 1200)
    config_loop = phase1.get("loop", 10)

    # CLI overrides > config values
    actual_loop = loop if loop is not None else config_loop
    actual_delay = (delay_ms if delay_ms is not None else config_delay_ms) / 1000.0

    results: List[ActionResult] = []

    logger.info(
        "Starting coordinate sequence — task=%s, coords=%d, loop=%d, delay=%.1fs, dry_run=%s",
        task_name,
        len(coordinates),
        actual_loop,
        actual_delay,
        dry_run,
    )

    for iteration in range(1, actual_loop + 1):
        logger.info("── Loop %d/%d ──", iteration, actual_loop)

        for coord in coordinates:
            x = coord["x"]
            y = coord["y"]
            label = coord.get("label", "unnamed")

            try:
                if dry_run:
                    logger.info(
                        "[DRY RUN] Would click (%d, %d) — %s", x, y, label
                    )
                else:
                    logger.info("Clicking (%d, %d) — %s", x, y, label)
                    pyautogui.click(x, y)

                time.sleep(actual_delay)

                results.append(
                    _build_result(
                        success=True,
                        action_taken=f"clicked {label} at ({x}, {y})",
                        coords={"x": x, "y": y},
                    )
                )

            except Exception as exc:
                logger.error("Action '%s' failed: %s", label, exc)
                results.append(
                    _build_result(
                        success=False,
                        action_taken=f"clicked {label} at ({x}, {y})",
                        coords={"x": x, "y": y},
                        error=str(exc),
                    )
                )

    logger.info(
        "Coordinate sequence complete — %d/%d succeeded",
        sum(1 for r in results if r["success"]),
        len(results),
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    # Run LinkedIn connect task in dry-run mode by default
    results = run_coordinate_sequence("linkedin_connect", dry_run=True, loop=2)
    for r in results:
        print(r)
