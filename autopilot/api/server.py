"""
server.py — Phase 5: FastAPI REST integration layer.

Exposes all automation phases as REST endpoints.
External projects (RelationOS, n8n, etc.) can call:
    POST /run-task { phase: 1|2|3|4, task: "linkedin_connect", params: {} }

Includes CORS middleware for the autopilot_panel.html UI panel.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from autopilot.actions.coordinate_runner import run_coordinate_sequence
from autopilot.actions.ocr_runner import run_ocr_sequence
from autopilot.actions.vision_runner import run_vision_sequence

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AutoPilot API",
    description="REST API for the AutoPilot computer-use automation agent",
    version="0.3.0",
)

# CORS — allow the local HTML panel to talk to the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyserParams(BaseModel):
    """Analyser-specific parameters for profile filtering."""

    enabled: bool = Field(default=False, description="Enable profile analysis before clicks")
    model: Optional[str] = Field(default=None, description="AI model: deepface | llava")
    gender: Optional[str] = Field(default=None, description="Gender filter: male | female | any")
    age_min: Optional[int] = Field(default=None, description="Minimum age filter")
    age_max: Optional[int] = Field(default=None, description="Maximum age filter")
    followers_min: Optional[int] = Field(default=None, description="Minimum follower count")
    followers_max: Optional[int] = Field(default=None, description="Maximum follower count")


class TaskRequest(BaseModel):
    """Request body for /run-task endpoint."""

    phase: int = Field(
        ...,
        ge=1,
        le=4,
        description="Automation phase to use: 1=Coordinates, 2=OCR, 3=Vision, 4=Mobile",
    )
    task: str = Field(
        ...,
        description="Task config name (e.g. 'linkedin_connect')",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional parameters — dry_run, loop, delay_ms, fallback_to_ocr, serial, targets, etc.",
    )
    analyser: Optional[AnalyserParams] = Field(
        default=None,
        description="Optional analyser parameters for profile filtering (Phase 6)",
    )


class TaskResponse(BaseModel):
    """Response body from /run-task endpoint."""

    phase: int
    task: str
    results: List[Dict[str, Any]]
    total_actions: int
    successful_actions: int
    analyser_stats: Optional[Dict[str, int]] = None


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "autopilot", "version": "0.3.0"}


@app.post("/run-task", response_model=TaskResponse)
async def run_task(request: TaskRequest) -> TaskResponse:
    """
    Execute an automation task using the specified phase.

    Phases:
        1 — Coordinate clicks (hardcoded x, y from config)
        2 — OCR-based clicks (screenshot → OCR → keyword match → click)
        3 — Vision AI clicks (screenshot → Claude Vision → JSON coords → click)
        4 — Mobile (Android via ADB/uiautomator2)

    Params (all optional):
        dry_run (bool) — Simulate only, no clicks
        loop (int) — Number of iterations
        delay_ms (int) — Delay between clicks in ms
        fallback_to_ocr (bool) — Phase 3: enable OCR fallback
        targets (list[str]) — Phase 4: tap targets
        serial (str) — Phase 4: device serial

    Analyser (optional, Phase 6):
        enabled (bool) — Enable profile analysis
        model (str) — deepface | llava
        gender (str) — male | female | any
        age_min/age_max (int) — Age range
        followers_min/followers_max (int) — Follower range
    """
    logger.info(
        "API request — phase=%d, task=%s, params=%s, analyser=%s",
        request.phase,
        request.task,
        request.params,
        request.analyser,
    )

    dry_run = request.params.get("dry_run", False)
    loop = request.params.get("loop")
    delay_ms = request.params.get("delay_ms")

    # Build analyser overrides from request
    analyser_enabled = False
    analyser_overrides = {}
    if request.analyser and request.analyser.enabled:
        analyser_enabled = True
        if request.analyser.model:
            analyser_overrides["model"] = request.analyser.model
        if request.analyser.gender:
            analyser_overrides["gender"] = request.analyser.gender
        if request.analyser.age_min is not None:
            analyser_overrides["age_min"] = request.analyser.age_min
        if request.analyser.age_max is not None:
            analyser_overrides["age_max"] = request.analyser.age_max
        if request.analyser.followers_min is not None:
            analyser_overrides["followers_min"] = request.analyser.followers_min
        if request.analyser.followers_max is not None:
            analyser_overrides["followers_max"] = request.analyser.followers_max

    try:
        if request.phase == 1:
            results = run_coordinate_sequence(
                task_name=request.task,
                dry_run=dry_run,
                loop=loop,
                delay_ms=delay_ms,
            )

        elif request.phase == 2:
            results = run_ocr_sequence(
                task_name=request.task,
                dry_run=dry_run,
                loop=loop,
                delay_ms=delay_ms,
                analyse=analyser_enabled,
                analyser_overrides=analyser_overrides if analyser_overrides else None,
            )

        elif request.phase == 3:
            fallback = request.params.get("fallback_to_ocr", True)
            results = run_vision_sequence(
                task_name=request.task,
                dry_run=dry_run,
                fallback_to_ocr=fallback,
                loop=loop,
                delay_ms=delay_ms,
            )

        elif request.phase == 4:
            # Mobile phase — uses targets from params or falls back to config
            from autopilot.mobile.android_runner import run_mobile_sequence

            targets = request.params.get("targets", ["Connect", "Send"])
            serial = request.params.get("serial")
            results = run_mobile_sequence(
                targets=targets,
                serial=serial,
                dry_run=dry_run,
            )

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid phase: {request.phase}. Must be 1-4.",
            )

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Task execution failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    successful = sum(1 for r in results if r.get("success"))

    # Build analyser stats if any results contain analyser data
    analyser_stats = None
    analyser_results = [r for r in results if r.get("analyser")]
    if analyser_results:
        analyser_stats = {
            "analysed": len(analyser_results),
            "connected": sum(
                1 for r in analyser_results
                if r.get("analyser", {}).get("action") == "connect"
            ),
            "skipped": sum(
                1 for r in analyser_results
                if r.get("analyser", {}).get("action") == "skip"
            ),
            "flagged": sum(
                1 for r in analyser_results
                if r.get("analyser", {}).get("action") == "flag"
            ),
        }

    return TaskResponse(
        phase=request.phase,
        task=request.task,
        results=results,
        total_actions=len(results),
        successful_actions=successful,
        analyser_stats=analyser_stats,
    )


@app.post("/analyse-profile")
async def analyse_profile_endpoint(
    params: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Run profile analysis on the current screen without performing any clicks.

    Useful for testing analyser configuration and crop regions.
    Returns the full AnalyserResult dict.
    """
    try:
        from autopilot.analyser.profile_analyser import analyse_profile
        from autopilot.actions.coordinate_runner import load_task_config

        task_name = (params or {}).get("task", "linkedin_connect")
        config = load_task_config(task_name)
        analyser_config = config.get("analyser", {})

        result = analyse_profile(
            analyser_config=analyser_config,
            dry_run=True,
        )
        return result

    except Exception as exc:
        logger.error("Profile analysis endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8000)
