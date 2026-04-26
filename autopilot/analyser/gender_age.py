"""
gender_age.py — Local AI gender and age estimation.

Primary: DeepFace (fully offline, CPU/GPU)
Fallback: Ollama + LLaVA (local multimodal LLM)

Both run 100% locally — no cloud API keys needed.
"""

import io
import json
import logging
import re
from typing import Any, Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)

# Result type
GenderAgeResult = Dict[str, Any]


def _default_result() -> GenderAgeResult:
    """Return a default result when analysis fails."""
    return {
        "gender": "unknown",
        "age": 0,
        "confidence": 0.0,
        "model_used": "none",
        "error": None,
    }


# ═══════════════════════════════════════════════
# DeepFace (primary)
# ═══════════════════════════════════════════════

def analyse_deepface(image: Image.Image) -> GenderAgeResult:
    """
    Analyse a profile photo using DeepFace for gender and age.

    DeepFace downloads models (~200MB) on first run and caches locally.
    Runs fully offline after that.

    Args:
        image: PIL Image of the cropped profile photo.

    Returns:
        GenderAgeResult dict with gender, age, confidence, model_used.
    """
    try:
        from deepface import DeepFace  # type: ignore[import-untyped]
    except ImportError:
        logger.error("deepface not installed — run: pip install deepface opencv-python-headless tf-keras")
        result = _default_result()
        result["error"] = "deepface not installed"
        return result

    try:
        import numpy as np  # type: ignore[import-untyped]

        # Convert PIL → numpy array (RGB)
        img_array = np.array(image.convert("RGB"))

        # DeepFace.analyze returns a list of face analyses
        analyses = DeepFace.analyze(
            img_path=img_array,
            actions=["gender", "age"],
            enforce_detection=False,  # Don't crash if no face found
            silent=True,
        )

        if not analyses:
            logger.warning("DeepFace returned no faces")
            result = _default_result()
            result["model_used"] = "deepface"
            result["error"] = "no face detected"
            return result

        # Take the first (most prominent) face
        face = analyses[0] if isinstance(analyses, list) else analyses

        # Gender: DeepFace returns {"Man": X, "Woman": Y} percentages
        gender_scores = face.get("gender", {})
        man_score = gender_scores.get("Man", 0)
        woman_score = gender_scores.get("Woman", 0)

        if woman_score > man_score:
            gender = "female"
            confidence = woman_score / 100.0
        elif man_score > woman_score:
            gender = "male"
            confidence = man_score / 100.0
        else:
            gender = "unknown"
            confidence = 0.5

        age = int(face.get("age", 0))

        logger.info(
            "DeepFace result — gender=%s (%.2f), age=%d",
            gender, confidence, age,
        )

        return {
            "gender": gender,
            "age": age,
            "confidence": round(confidence, 3),
            "model_used": "deepface",
            "error": None,
        }

    except Exception as exc:
        logger.error("DeepFace analysis failed: %s", exc)
        result = _default_result()
        result["model_used"] = "deepface"
        result["error"] = str(exc)
        return result


# ═══════════════════════════════════════════════
# LLaVA via Ollama (fallback)
# ═══════════════════════════════════════════════

def analyse_llava(
    image: Image.Image,
    endpoint: str = "http://localhost:11434/api/generate",
    model: str = "llava",
) -> GenderAgeResult:
    """
    Analyse a profile photo using LLaVA via local Ollama.

    Sends the image to the local Ollama endpoint and asks for
    gender/age analysis in JSON format.

    Args:
        image: PIL Image of the cropped profile photo.
        endpoint: Ollama API endpoint (default: localhost:11434).
        model: Ollama model name (default: llava).

    Returns:
        GenderAgeResult dict.
    """
    try:
        import base64
        import requests  # type: ignore[import-untyped]
    except ImportError:
        logger.error("requests not installed — run: pip install requests")
        result = _default_result()
        result["error"] = "requests not installed"
        return result

    try:
        # Encode image to base64
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        b64_image = base64.b64encode(buffer.getvalue()).decode("utf-8")

        prompt = (
            "Analyze this profile photo. Return ONLY a JSON object with exactly these fields: "
            '{"gender": "male" or "female" or "unknown", "age_estimate": integer, "confidence": float 0-1}. '
            "No other text."
        )

        payload = {
            "model": model,
            "prompt": prompt,
            "images": [b64_image],
            "stream": False,
        }

        logger.info("Sending image to LLaVA at %s", endpoint)

        response = requests.post(endpoint, json=payload, timeout=30)
        response.raise_for_status()

        raw_text = response.json().get("response", "").strip()
        logger.debug("LLaVA raw response: %s", raw_text)

        return _parse_llava_response(raw_text)

    except Exception as exc:
        logger.error("LLaVA analysis failed: %s", exc)
        result = _default_result()
        result["model_used"] = "llava"
        result["error"] = str(exc)
        return result


def _parse_llava_response(raw_text: str) -> GenderAgeResult:
    """
    Parse LLaVA JSON response into a GenderAgeResult.

    Handles markdown code fences and partial JSON.

    Args:
        raw_text: Raw text response from LLaVA.

    Returns:
        Parsed GenderAgeResult dict.
    """
    text = raw_text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]).strip()

    # Try to find JSON in the response
    json_match = re.search(r'\{[^}]+\}', text)
    if not json_match:
        logger.error("No JSON found in LLaVA response: %s", raw_text)
        result = _default_result()
        result["model_used"] = "llava"
        result["error"] = "no JSON in response"
        return result

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        logger.error("Failed to parse LLaVA JSON: %s", json_match.group())
        result = _default_result()
        result["model_used"] = "llava"
        result["error"] = "invalid JSON"
        return result

    gender = str(data.get("gender", "unknown")).lower()
    if gender not in ("male", "female", "unknown"):
        gender = "unknown"

    age = int(data.get("age_estimate", data.get("age", 0)))
    confidence = float(data.get("confidence", 0.0))

    logger.info("LLaVA result — gender=%s (%.2f), age=%d", gender, confidence, age)

    return {
        "gender": gender,
        "age": age,
        "confidence": round(confidence, 3),
        "model_used": "llava",
        "error": None,
    }


# ═══════════════════════════════════════════════
# Unified entry point
# ═══════════════════════════════════════════════

def analyse(
    image: Image.Image,
    model: str = "deepface",
    llava_endpoint: str = "http://localhost:11434/api/generate",
    llava_model: str = "llava",
    min_confidence: float = 0.5,
) -> GenderAgeResult:
    """
    Analyse a profile photo for gender and age using the configured model.

    Strategy: Try primary model first. If it fails or confidence is below
    threshold, try the fallback model. If both fail, return unknown.

    Args:
        image: PIL Image of the cropped profile photo.
        model: Primary model — "deepface" or "llava".
        llava_endpoint: Ollama endpoint for LLaVA fallback.
        llava_model: Ollama model name.
        min_confidence: Minimum confidence to accept a result.

    Returns:
        GenderAgeResult dict.
    """
    logger.info("Starting gender/age analysis — primary model: %s", model)

    if model == "deepface":
        result = analyse_deepface(image)

        # If DeepFace fails or low confidence, try LLaVA
        if result.get("error") or result.get("confidence", 0) < min_confidence:
            logger.info(
                "DeepFace result insufficient (conf=%.2f) — trying LLaVA fallback",
                result.get("confidence", 0),
            )
            fallback = analyse_llava(image, endpoint=llava_endpoint, model=llava_model)
            if not fallback.get("error"):
                return fallback

        return result

    elif model == "llava":
        result = analyse_llava(image, endpoint=llava_endpoint, model=llava_model)

        # If LLaVA fails, try DeepFace
        if result.get("error"):
            logger.info("LLaVA failed — trying DeepFace fallback")
            return analyse_deepface(image)

        return result

    else:
        logger.error("Unknown model: %s — defaulting to deepface", model)
        return analyse_deepface(image)
