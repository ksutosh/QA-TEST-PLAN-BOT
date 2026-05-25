from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger
from app.services.test_plan_pipeline import process_app_mention_event

logger = get_logger(__name__)

router = APIRouter(tags=["slack"])


@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as exc:
        logger.exception("Invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    payload_type = payload.get("type")
    logger.info("Slack POST type=%s", payload_type)

    if payload_type == "url_verification":
        challenge = payload.get("challenge")
        if not challenge:
            raise HTTPException(status_code=400, detail="Missing challenge")
        return JSONResponse({"challenge": challenge})

    if payload_type != "event_callback":
        return JSONResponse({"ok": True})

    event: Dict[str, Any] = dict(payload.get("event") or {})
    event_id = payload.get("event_id")
    event_type = event.get("type")
    logger.info("event_callback event_id=%s event.type=%s", event_id, event_type)

    if event_type != "app_mention":
        return JSONResponse({"ok": True})

    if event.get("bot_id"):
        return JSONResponse({"ok": True})

    background_tasks.add_task(process_app_mention_event, event)
    return JSONResponse({"ok": True})
