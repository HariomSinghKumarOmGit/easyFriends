# SKILL: AutoPilot — Computer Use Automation Agent

## What This Is
A phased Python automation agent for UI task automation.
Desktop-first, mobile-ready, AI-vision-enhanced, API-integrated.

## Tech Stack
| Layer | Tool |
|---|---|
| Mouse/keyboard | PyAutoGUI |
| OCR | pytesseract + Pillow |
| Vision AI | Claude Vision API |
| Mobile | ADB + uiautomator2 |
| API layer | FastAPI |
| Scheduler | n8n (optional) |

## Phases
1. Coordinate clicks — hardcoded (x,y) sequences from config
2. OCR clicks — screenshot → refine text → keyword match → click
3. Vision AI — screenshot → Claude Vision → JSON coords → click
4. Mobile — ADB/uiautomator2 mirror of above phases
5. Integration — FastAPI REST wrapper for external project calls

## OCR Pipeline
raw OCR → lowercase → strip noise → regex clean →
filter confidence > 60 → extract bounding box center → click

## Vision AI Call Pattern
screenshot → base64 → Claude Vision API →
"Return JSON {x, y} for [button]" → parse → click

## Structured Response Shape (all runners)
{
  success: bool,
  action_taken: str,
  coords: {x, y} | null,
  error: str | null
}

## Current Task Being Built
LinkedIn connection request automation
Targets: "Connect" → click → "Send" → click → loop
Phase: 1 + 2 combined

## Integration Points
- Other projects call POST /run-task on FastAPI server
- n8n triggers scheduled runs
- RelationOS or any project can plug in via HTTP

## Key Rules
- Config over hardcoding
- Confidence threshold: 60 (OCR)
- Vision is primary intelligence, OCR + coords are fallbacks
- Never crash silently — structured error returns always
- Logging > print()