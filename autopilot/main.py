"""
main.py — AutoPilot CLI entry point.

Runs any phase against any task config from the command line.

Usage:
    python -m autopilot.main run --phase 1 --task linkedin_connect --dry-run
    python -m autopilot.main run --phase 2 --task linkedin_connect --loop 25 --delay 1000
    python -m autopilot.main run --phase 3 --task linkedin_connect --no-fallback
    python -m autopilot.main run --phase 2 --task linkedin_connect --analyse --gender female --age-min 22 --age-max 38
    python -m autopilot.main serve                              # start FastAPI server
"""

import argparse
import json
import logging
import sys
from typing import Any, Dict, List

logger = logging.getLogger("autopilot")


def setup_logging(verbose: bool = False) -> None:
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def print_results(results: List[Dict[str, Any]]) -> None:
    """Pretty-print a list of action results."""
    for i, result in enumerate(results, 1):
        status = "✅" if result["success"] else "❌"
        coords = result.get("coords")
        coord_str = f"({coords['x']}, {coords['y']})" if coords else "—"
        phase = result.get("phase_used", "?")
        error = result.get("error", "")

        print(f"  {status} [{i}] P{phase} {result['action_taken']:<40} coords={coord_str}")
        if error:
            print(f"       ⚠️  {error}")

        # Print analyser info if present
        analyser = result.get("analyser")
        if analyser:
            print(
                f"       🔍 gender={analyser.get('gender','?')} "
                f"age={analyser.get('age',0)} "
                f"followers={analyser.get('followers',0):,} "
                f"→ {analyser.get('action','?')} ({analyser.get('reason','')})"
            )

    total = len(results)
    passed = sum(1 for r in results if r["success"])
    print(f"\n  Result: {passed}/{total} actions succeeded")

    # Print analyser summary if any results have analyser data
    analyser_results = [r for r in results if r.get("analyser")]
    if analyser_results:
        analysed = len(analyser_results)
        skipped = sum(1 for r in analyser_results if r.get("analyser", {}).get("action") == "skip")
        connected = sum(1 for r in analyser_results if r.get("analyser", {}).get("action") == "connect")
        flagged = sum(1 for r in analyser_results if r.get("analyser", {}).get("action") == "flag")
        print(f"  Analyser: {analysed} analysed | {connected} connect | {skipped} skip | {flagged} flag")


def run_phase(args: argparse.Namespace) -> None:
    """Execute the requested phase."""
    phase = args.phase
    task = args.task
    dry_run = args.dry_run
    loop = args.loop
    delay = args.delay

    print(f"\n🤖 AutoPilot — Phase {phase} — Task: {task}")
    mode = "[DRY RUN]" if dry_run else "[LIVE]"
    loop_str = f"loop={loop}" if loop else "loop=config"
    delay_str = f"delay={delay}ms" if delay else "delay=config"
    analyse_str = " | analyser=ON" if getattr(args, "analyse", False) else ""
    print(f"   {mode} | {loop_str} | {delay_str}{analyse_str}\n")

    if phase == 1:
        from autopilot.actions.coordinate_runner import run_coordinate_sequence

        results = run_coordinate_sequence(
            task_name=task, dry_run=dry_run, loop=loop, delay_ms=delay
        )

    elif phase == 2:
        from autopilot.actions.ocr_runner import run_ocr_sequence

        # Build analyser overrides from CLI flags
        analyser_overrides = _build_analyser_overrides(args)

        results = run_ocr_sequence(
            task_name=task,
            dry_run=dry_run,
            loop=loop,
            delay_ms=delay,
            analyse=getattr(args, "analyse", False),
            analyser_overrides=analyser_overrides,
        )

    elif phase == 3:
        from autopilot.actions.vision_runner import run_vision_sequence

        fallback = not args.no_fallback
        results = run_vision_sequence(
            task_name=task,
            dry_run=dry_run,
            fallback_to_ocr=fallback,
            loop=loop,
            delay_ms=delay,
        )

    elif phase == 4:
        from autopilot.mobile.android_runner import run_mobile_sequence

        targets = args.targets.split(",") if args.targets else ["Connect", "Send"]
        results = run_mobile_sequence(
            targets=targets, serial=args.serial, dry_run=dry_run
        )

    else:
        print(f"❌ Invalid phase: {phase}")
        sys.exit(1)

    print_results(results)

    # Optionally output as JSON
    if args.json:
        print(f"\n📋 JSON output:")
        print(json.dumps(results, indent=2))


def _build_analyser_overrides(args: argparse.Namespace) -> Dict[str, Any]:
    """
    Build analyser override dict from CLI flags.

    Maps --gender, --age-min, --age-max, --followers-min, --followers-max,
    --model flags to the analyser_overrides dict consumed by ocr_runner.
    """
    overrides: Dict[str, Any] = {}

    if hasattr(args, "gender") and args.gender:
        overrides["gender"] = args.gender
    if hasattr(args, "age_min") and args.age_min is not None:
        overrides["age_min"] = args.age_min
    if hasattr(args, "age_max") and args.age_max is not None:
        overrides["age_max"] = args.age_max
    if hasattr(args, "followers_min") and args.followers_min is not None:
        overrides["followers_min"] = args.followers_min
    if hasattr(args, "followers_max") and args.followers_max is not None:
        overrides["followers_max"] = args.followers_max
    if hasattr(args, "model") and args.model:
        overrides["model"] = args.model

    return overrides


def serve(args: argparse.Namespace) -> None:
    """Start the FastAPI server."""
    try:
        import uvicorn
    except ImportError:
        print("❌ uvicorn not installed — run: pip install uvicorn")
        sys.exit(1)

    print(f"\n🚀 Starting AutoPilot API server on {args.host}:{args.port}")
    uvicorn.run(
        "autopilot.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate handler."""
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="AutoPilot — Computer Use Automation Agent",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── run command ──
    run_parser = subparsers.add_parser("run", help="Run an automation task")
    run_parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3, 4],
        required=True,
        help="Automation phase (1=Coords, 2=OCR, 3=Vision, 4=Mobile)",
    )
    run_parser.add_argument(
        "--task",
        type=str,
        required=True,
        help="Task config name (e.g. linkedin_connect)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log actions without clicking",
    )
    run_parser.add_argument(
        "--loop",
        type=int,
        default=None,
        help="Number of loop iterations (default: from config, usually 10)",
    )
    run_parser.add_argument(
        "--delay",
        type=int,
        default=None,
        help="Delay between clicks in milliseconds (default: from config, usually 1200)",
    )
    run_parser.add_argument(
        "--no-fallback",
        action="store_true",
        default=False,
        help="Phase 3 only: disable OCR fallback",
    )
    run_parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Phase 4 only: comma-separated tap targets",
    )
    run_parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help="Phase 4 only: Android device serial or IP:port",
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Also output results as JSON",
    )
    run_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )

    # ── Analyser flags (Phase 6) ──
    analyser_group = run_parser.add_argument_group(
        "analyser", "Profile analysis options (Phase 6)"
    )
    analyser_group.add_argument(
        "--analyse",
        action="store_true",
        default=False,
        help="Enable profile analysis pass before clicks",
    )
    analyser_group.add_argument(
        "--gender",
        type=str,
        default=None,
        choices=["male", "female", "any"],
        help="Override YAML — only connect to this gender",
    )
    analyser_group.add_argument(
        "--age-min",
        type=int,
        default=None,
        dest="age_min",
        help="Override YAML — minimum age filter",
    )
    analyser_group.add_argument(
        "--age-max",
        type=int,
        default=None,
        dest="age_max",
        help="Override YAML — maximum age filter",
    )
    analyser_group.add_argument(
        "--followers-min",
        type=int,
        default=None,
        dest="followers_min",
        help="Override YAML — minimum follower count",
    )
    analyser_group.add_argument(
        "--followers-max",
        type=int,
        default=None,
        dest="followers_max",
        help="Override YAML — maximum follower count",
    )
    analyser_group.add_argument(
        "--model",
        type=str,
        default=None,
        choices=["deepface", "llava"],
        help="Override YAML — AI model for analysis (deepface or llava)",
    )

    run_parser.set_defaults(func=run_phase)

    # ── serve command ──
    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI server")
    serve_parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="Bind host"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8000, help="Bind port"
    )
    serve_parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload for development",
    )
    serve_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        default=False,
        help="Enable debug logging",
    )
    serve_parser.set_defaults(func=serve)

    # Parse and dispatch
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    setup_logging(verbose=args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()
