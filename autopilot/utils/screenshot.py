"""
screenshot.py — Capture screenshots for OCR and Vision AI pipelines.

Uses PyAutoGUI to grab full or partial screen captures.
Returns PIL Image objects for downstream processing.
"""

import logging
from typing import Optional, Tuple

import pyautogui
from PIL import Image

logger = logging.getLogger(__name__)


def take_screenshot(
    region: Optional[Tuple[int, int, int, int]] = None,
    save_path: Optional[str] = None,
) -> Image.Image:
    """
    Capture a screenshot of the screen (or a region).

    Args:
        region: Optional (left, top, width, height) tuple to capture a sub-region.
                None captures the full screen.
        save_path: Optional file path to save the screenshot to disk.

    Returns:
        PIL Image of the captured screen area.

    Raises:
        RuntimeError: If screenshot capture fails.
    """
    try:
        logger.info(
            "Capturing screenshot — region=%s, save_path=%s",
            region,
            save_path,
        )
        screenshot: Image.Image = pyautogui.screenshot(region=region)

        if save_path:
            screenshot.save(save_path)
            logger.info("Screenshot saved to %s", save_path)

        return screenshot

    except Exception as exc:
        logger.error("Screenshot capture failed: %s", exc)
        raise RuntimeError(f"Failed to capture screenshot: {exc}") from exc


def get_screen_size() -> Tuple[int, int]:
    """
    Return the current screen resolution as (width, height).
    """
    size = pyautogui.size()
    logger.debug("Screen size: %dx%d", size.width, size.height)
    return (size.width, size.height)
