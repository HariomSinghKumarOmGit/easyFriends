"""
crop_utils.py — Crop regions from screenshots for profile analysis.

Extracts specific pixel regions (profile photo, follower text) from
full screenshots based on configurable crop coordinates from YAML.
"""

import logging
from typing import Dict, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


def crop_region(
    image: Image.Image,
    region: Dict[str, int],
) -> Optional[Image.Image]:
    """
    Crop a rectangular region from a PIL Image.

    Args:
        image: Source PIL Image (full screenshot).
        region: Dict with keys: x, y, width, height (pixels).

    Returns:
        Cropped PIL Image, or None if crop fails.
    """
    try:
        x = region["x"]
        y = region["y"]
        w = region["width"]
        h = region["height"]

        # Clamp to image bounds
        img_w, img_h = image.size
        x = max(0, min(x, img_w - 1))
        y = max(0, min(y, img_h - 1))
        x2 = min(x + w, img_w)
        y2 = min(y + h, img_h)

        if x2 <= x or y2 <= y:
            logger.error(
                "Invalid crop region after clamping: (%d,%d,%d,%d) on %dx%d image",
                x, y, x2, y2, img_w, img_h,
            )
            return None

        cropped = image.crop((x, y, x2, y2))
        logger.debug(
            "Cropped region (%d,%d,%d,%d) → %dx%d",
            x, y, x2, y2, cropped.width, cropped.height,
        )
        return cropped

    except Exception as exc:
        logger.error("Crop failed: %s", exc)
        return None


def crop_from_screenshot(
    screenshot: Image.Image,
    photo_region: Optional[Dict[str, int]] = None,
    follower_region: Optional[Dict[str, int]] = None,
) -> Tuple[Optional[Image.Image], Optional[Image.Image]]:
    """
    Crop both profile photo and follower text regions from a screenshot.

    Args:
        screenshot: Full-screen PIL Image.
        photo_region: Crop config for profile photo area.
        follower_region: Crop config for follower count text area.

    Returns:
        Tuple of (photo_crop, follower_crop). Either can be None if
        the region config is missing or crop fails.
    """
    photo_crop = None
    follower_crop = None

    if photo_region:
        photo_crop = crop_region(screenshot, photo_region)
        if photo_crop:
            logger.info("Profile photo cropped: %dx%d", photo_crop.width, photo_crop.height)
        else:
            logger.warning("Failed to crop profile photo region")

    if follower_region:
        follower_crop = crop_region(screenshot, follower_region)
        if follower_crop:
            logger.info("Follower region cropped: %dx%d", follower_crop.width, follower_crop.height)
        else:
            logger.warning("Failed to crop follower count region")

    return photo_crop, follower_crop
