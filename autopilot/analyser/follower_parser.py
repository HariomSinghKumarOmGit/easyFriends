"""
follower_parser.py — Extract follower/connection count from screenshot via OCR.

Pipeline:
    1. Receive cropped image of the follower text region
    2. Run pytesseract OCR
    3. Regex match: r'([\d,]+)\s*(followers?|connections?)'
    4. Parse to integer
"""

import logging
import re
from typing import Any, Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)

# Patterns to match follower/connection counts
FOLLOWER_PATTERNS = [
    # "3,200 followers" or "3200 followers"
    re.compile(r'([\d,]+)\s*(?:followers?)', re.IGNORECASE),
    # "1,500 connections"
    re.compile(r'([\d,]+)\s*(?:connections?)', re.IGNORECASE),
    # "3.2K followers" or "3.2k connections"
    re.compile(r'([\d.]+)\s*[kK]\s*(?:followers?|connections?)', re.IGNORECASE),
    # "1.2M followers"
    re.compile(r'([\d.]+)\s*[mM]\s*(?:followers?|connections?)', re.IGNORECASE),
    # Standalone number with comma formatting (fallback)
    re.compile(r'([\d,]{3,})', re.IGNORECASE),
]

# Result type
FollowerResult = Dict[str, Any]


def parse_follower_count(image: Image.Image) -> FollowerResult:
    """
    Extract follower/connection count from a cropped screenshot region.

    Args:
        image: PIL Image of the follower text area (cropped).

    Returns:
        Dict with keys: count (int), raw_text (str), error (str|None).
    """
    try:
        import pytesseract  # type: ignore[import-untyped]
    except ImportError:
        logger.error("pytesseract not installed")
        return {"count": 0, "raw_text": "", "error": "pytesseract not installed"}

    try:
        # Run OCR
        raw_text = pytesseract.image_to_string(image).strip()
        logger.debug("Follower OCR raw text: '%s'", raw_text)

        if not raw_text:
            return {"count": 0, "raw_text": "", "error": "OCR returned empty text"}

        # Try each pattern
        for pattern in FOLLOWER_PATTERNS:
            match = pattern.search(raw_text)
            if match:
                count = _parse_number(match.group(1), raw_text, pattern)
                if count is not None and count > 0:
                    logger.info(
                        "Follower count parsed: %d (from: '%s')",
                        count, match.group(0),
                    )
                    return {
                        "count": count,
                        "raw_text": raw_text,
                        "error": None,
                    }

        logger.warning("No follower count found in OCR text: '%s'", raw_text)
        return {"count": 0, "raw_text": raw_text, "error": "no count pattern matched"}

    except Exception as exc:
        logger.error("Follower parsing failed: %s", exc)
        return {"count": 0, "raw_text": "", "error": str(exc)}


def _parse_number(
    num_str: str,
    full_text: str,
    pattern: re.Pattern,
) -> Optional[int]:
    """
    Parse a number string into an integer, handling commas and K/M suffixes.

    Args:
        num_str: The matched number string (e.g. "3,200" or "3.2").
        full_text: The full OCR text for context.
        pattern: The pattern that matched (to determine K/M handling).

    Returns:
        Integer count, or None if parsing fails.
    """
    try:
        # Check for K suffix
        if re.search(r'[kK]\s*(?:followers?|connections?)', full_text):
            num = float(num_str.replace(",", ""))
            return int(num * 1000)

        # Check for M suffix
        if re.search(r'[mM]\s*(?:followers?|connections?)', full_text):
            num = float(num_str.replace(",", ""))
            return int(num * 1_000_000)

        # Standard integer with optional commas
        return int(num_str.replace(",", ""))

    except (ValueError, TypeError) as exc:
        logger.debug("Number parsing failed for '%s': %s", num_str, exc)
        return None
