"""
android_runner.py — Phase 4: Android mobile automation.

Uses ADB + uiautomator2 to mirror Phase 1-3 logic on Android devices.
Supports element finding by text/resource-id and tapping.

NOTE: Requires an Android device connected via USB or TCP/IP with
      USB debugging enabled.
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Structured response type
ActionResult = Dict[str, Any]


def _build_result(
    success: bool,
    action_taken: str,
    coords: Optional[Dict[str, int]] = None,
    error: Optional[str] = None,
) -> ActionResult:
    """Build a standardized action result dict."""
    return {
        "success": success,
        "action_taken": action_taken,
        "coords": coords,
        "error": error,
    }


def connect_device(serial: Optional[str] = None) -> Any:
    """
    Connect to an Android device via uiautomator2.

    Args:
        serial: Device serial or IP:port. None = auto-detect first device.

    Returns:
        uiautomator2 device object.

    Raises:
        ImportError: If uiautomator2 is not installed.
        ConnectionError: If device cannot be reached.
    """
    try:
        import uiautomator2 as u2  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "uiautomator2 not installed — run: pip install uiautomator2"
        )
        raise

    try:
        if serial:
            device = u2.connect(serial)
        else:
            device = u2.connect()

        info = device.info
        logger.info(
            "Connected to device: %s (%s)",
            info.get("productName", "unknown"),
            info.get("displaySizeDpX", "?"),
        )
        return device

    except Exception as exc:
        logger.error("Failed to connect to Android device: %s", exc)
        raise ConnectionError(f"Device connection failed: {exc}") from exc


def tap_by_text(
    device: Any,
    text: str,
    timeout: float = 5.0,
    delay_after: float = 1.2,
    dry_run: bool = False,
) -> ActionResult:
    """
    Find a UI element by text and tap it.

    Args:
        device: uiautomator2 device object.
        text: Text label of the element to tap.
        timeout: Max time to wait for the element to appear (seconds).
        delay_after: Delay after tapping (seconds).
        dry_run: If True, don't actually tap.

    Returns:
        ActionResult dict.
    """
    logger.info("Looking for element with text='%s' (timeout=%.1fs)", text, timeout)

    try:
        element = device(text=text)

        if not element.wait(timeout=timeout):
            return _build_result(
                success=False,
                action_taken=f"mobile_tap_{text}",
                error=f"Element with text '{text}' not found within {timeout}s",
            )

        bounds = element.info.get("bounds", {})
        cx = (bounds.get("left", 0) + bounds.get("right", 0)) // 2
        cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2

        if dry_run:
            logger.info("[DRY RUN] Would tap '%s' at (%d, %d)", text, cx, cy)
        else:
            logger.info("Tapping '%s' at (%d, %d)", text, cx, cy)
            element.click()

        time.sleep(delay_after)

        return _build_result(
            success=True,
            action_taken=f"mobile_tap_{text}",
            coords={"x": cx, "y": cy},
        )

    except Exception as exc:
        logger.error("Mobile tap failed for '%s': %s", text, exc)
        return _build_result(
            success=False,
            action_taken=f"mobile_tap_{text}",
            error=str(exc),
        )


def run_mobile_sequence(
    targets: List[str],
    serial: Optional[str] = None,
    dry_run: bool = False,
) -> List[ActionResult]:
    """
    Run a sequence of text-based taps on an Android device.

    Args:
        targets: List of text labels to tap in order.
        serial: Device serial or IP:port.
        dry_run: If True, don't actually tap.

    Returns:
        List of ActionResult dicts.
    """
    device = connect_device(serial=serial)
    results: List[ActionResult] = []

    for text in targets:
        result = tap_by_text(device, text, dry_run=dry_run)
        results.append(result)

        if not result["success"]:
            logger.warning("Stopping mobile sequence — '%s' not found", text)
            break

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    # Example usage — change targets as needed
    results = run_mobile_sequence(
        targets=["Connect", "Send"],
        dry_run=True,
    )
    for r in results:
        print(r)
