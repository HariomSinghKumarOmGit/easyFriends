"""
vision_utils.py — Claude Vision API integration utilities.

Pipeline: screenshot → base64 encode → Claude Vision API →
          parse JSON {x, y} → return coordinates
"""

import base64
import io
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# Model for vision calls
VISION_MODEL = "claude-sonnet-4-20250514"


def image_to_base64(image: Image.Image, fmt: str = "PNG") -> str:
    """
    Encode a PIL Image to a base64 string.

    Args:
        image: PIL Image to encode.
        fmt: Image format (PNG, JPEG, etc.).

    Returns:
        Base64-encoded string of the image.
    """
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    b64 = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")
    logger.debug("Image encoded to base64 — format=%s, length=%d", fmt, len(b64))
    return b64


def ask_vision_for_coords(
    image: Image.Image,
    target_description: str,
    api_key: Optional[str] = None,
) -> Optional[Tuple[int, int]]:
    """
    Send a screenshot to Claude Vision API and ask for the pixel coordinates
    of a target UI element.

    Args:
        image: PIL Image (screenshot) to analyze.
        target_description: What to find, e.g. "the blue 'Connect' button".
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        (x, y) tuple if the element was found, None otherwise.
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        logger.error("No ANTHROPIC_API_KEY provided — vision call skipped")
        return None

    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError:
        logger.error("anthropic package not installed — run: pip install anthropic")
        return None

    b64_image = image_to_base64(image)

    prompt = (
        f"Look at this screenshot carefully. "
        f"Find the UI element described as: \"{target_description}\". "
        f"Return ONLY a JSON object with the exact pixel coordinates of its center: "
        f'{{ "x": <int>, "y": <int> }}. '
        f"If the element is not visible, return: {{ \"x\": null, \"y\": null }}."
    )

    logger.info("Sending vision request — target: '%s'", target_description)

    try:
        client = anthropic.Anthropic(api_key=key)
        response = client.messages.create(
            model=VISION_MODEL,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        # Extract text from response
        raw_text = response.content[0].text.strip()
        logger.debug("Vision API raw response: %s", raw_text)

        coords = _parse_coords(raw_text)
        return coords

    except Exception as exc:
        logger.error("Vision API call failed: %s", exc)
        return None


def _parse_coords(raw_text: str) -> Optional[Tuple[int, int]]:
    """
    Parse JSON coordinates from Claude Vision response.

    Handles cases where the model wraps JSON in markdown code fences.

    Args:
        raw_text: Raw text response from the API.

    Returns:
        (x, y) tuple if valid coordinates found, None otherwise.
    """
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (the fences)
        text = "\n".join(lines[1:-1]).strip()

    try:
        data: Dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON from vision response: %s", raw_text)
        return None

    x = data.get("x")
    y = data.get("y")

    if x is None or y is None:
        logger.warning("Vision API reported element not found (null coords)")
        return None

    try:
        return (int(x), int(y))
    except (ValueError, TypeError):
        logger.error("Invalid coordinate values: x=%s, y=%s", x, y)
        return None
