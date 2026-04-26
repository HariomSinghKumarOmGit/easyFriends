"""
ocr_utils.py — OCR pipeline utilities.

Pipeline: raw OCR → lowercase → strip noise → regex clean →
          filter confidence > threshold → extract bounding box center
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

# Default confidence threshold (0-100)
DEFAULT_CONFIDENCE = 60


@dataclass
class OCRWord:
    """A single recognized word with its bounding box and confidence."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        """Return the center (x, y) of the bounding box."""
        return (self.left + self.width // 2, self.top + self.height // 2)


def extract_words(
    image: Image.Image,
    confidence_threshold: int = DEFAULT_CONFIDENCE,
) -> List[OCRWord]:
    """
    Run OCR on a PIL Image and return cleaned, filtered word results.

    Pipeline:
        1. pytesseract.image_to_data() → raw word data
        2. Filter out entries with no text or low confidence
        3. Clean text: lowercase, strip whitespace, regex remove non-alpha noise
        4. Return list of OCRWord objects

    Args:
        image: PIL Image to process.
        confidence_threshold: Minimum confidence (0-100) to keep a word.

    Returns:
        List of OCRWord objects that passed the confidence filter.
    """
    logger.info(
        "Running OCR pipeline — confidence_threshold=%d", confidence_threshold
    )

    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception as exc:
        logger.error("pytesseract failed: %s", exc)
        return []

    words: List[OCRWord] = []
    n_entries = len(data["text"])

    for i in range(n_entries):
        raw_text = data["text"][i]
        conf = data["conf"][i]

        # Skip empty entries or entries where conf is -1 (non-word regions)
        if not raw_text or not raw_text.strip():
            continue
        try:
            conf_val = float(conf)
        except (ValueError, TypeError):
            continue
        if conf_val < 0:
            continue

        # Clean: lowercase, strip, remove non-alpha characters
        cleaned = raw_text.strip().lower()
        cleaned = re.sub(r"[^a-z0-9]", "", cleaned)

        if not cleaned:
            continue

        if conf_val < confidence_threshold:
            logger.debug(
                "Skipping low-confidence word: '%s' (conf=%.1f)", cleaned, conf_val
            )
            continue

        word = OCRWord(
            text=cleaned,
            confidence=conf_val,
            left=int(data["left"][i]),
            top=int(data["top"][i]),
            width=int(data["width"][i]),
            height=int(data["height"][i]),
        )
        words.append(word)
        logger.debug(
            "OCR word: '%s' conf=%.1f bbox=(%d,%d,%d,%d)",
            word.text,
            word.confidence,
            word.left,
            word.top,
            word.width,
            word.height,
        )

    logger.info("OCR pipeline complete — %d words passed threshold", len(words))
    return words


def find_keyword(
    words: List[OCRWord],
    keyword: str,
) -> Optional[OCRWord]:
    """
    Find the first OCRWord matching a keyword (case-insensitive, cleaned).

    Args:
        words: List of OCRWord objects from extract_words().
        keyword: Target keyword to search for.

    Returns:
        The first matching OCRWord, or None if not found.
    """
    target = keyword.strip().lower()
    target = re.sub(r"[^a-z0-9]", "", target)

    for word in words:
        if word.text == target:
            logger.info(
                "Keyword '%s' found at center=(%d, %d) conf=%.1f",
                target,
                word.center[0],
                word.center[1],
                word.confidence,
            )
            return word

    logger.warning("Keyword '%s' not found in OCR results", target)
    return None
