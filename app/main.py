from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI

from app.api.slack_events import router as slack_events_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        settings = get_settings()
        setup_logging(settings.log_level)
        logger.info(
            "App started (jira=%s confluence=%s)",
            bool(settings.jira_api_base),
            bool(settings.confluence_api_base),
        )
    except Exception as exc:
        logger.error("Configuration error on startup: %s", exc)
        raise
    yield
    logger.info("App shutting down")


def create_app() -> FastAPI:
    application = FastAPI(title="Slack QA Test Plan Bot", lifespan=lifespan)
    application.include_router(slack_events_router)

    @application.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
