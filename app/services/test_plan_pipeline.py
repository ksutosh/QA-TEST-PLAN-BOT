from typing import Any, Dict, Optional

import markdown as md

from app.clients.confluence_client import create_confluence_page
from app.clients.llm_client import generate_test_plan_markdown
from app.clients.slack_client import (
    clean_and_combine_thread,
    fetch_thread_messages,
    post_thread_reply,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.context_resolver import resolve_context
from app.utils.formatter import save_html_file

logger = get_logger(__name__)

_NO_CONTENT_MESSAGE = (
    "No content found. Add a Confluence wiki link, JIRA issue key or browse link "
    "(e.g. SCRUM-5), upload a document in the thread (.md, .txt, .pdf, .docx, etc.), "
    "or post meaningful Slack thread context."
)


def _publish_test_plan(
    context: str,
    channel: str,
    thread_ts: str,
    settings: Settings,
) -> str:
    """Shared path: LLM → HTML file → new Confluence page → return local file path."""
    plan_markdown = generate_test_plan_markdown(
        thread_content=context,
        settings=settings,
    )
    html_content = md.markdown(plan_markdown)
    file_path = save_html_file(html_content, output_dir=settings.output_dir)
    create_confluence_page(content=html_content, settings=settings)
    post_thread_reply(
        bot_token=settings.slack_bot_token,
        channel=channel,
        thread_ts=thread_ts,
        message=f"✅ Test plan created: {file_path}",
    )
    return file_path


def process_app_mention_event(event: Dict[str, Any], settings: Optional[Settings] = None) -> None:
    """
    Coordinator: load Slack thread → resolve context → generate and publish test plan.
    """
    cfg = settings or get_settings()
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not channel or not thread_ts:
        logger.error(
            "app_mention missing channel or ts/thread_ts: keys=%s", list(event.keys())
        )
        return

    try:
        logger.info(
            "Processing app_mention channel=%s thread_ts=%s user=%s",
            channel,
            thread_ts,
            event.get("user"),
        )

        thread_messages = fetch_thread_messages(
            bot_token=cfg.slack_bot_token,
            channel=channel,
            thread_ts=thread_ts,
        )
        slack_text = clean_and_combine_thread(messages=thread_messages)
        mention_text = (event.get("text") or "").strip()

        context = resolve_context(
            mention_text, slack_text, cfg, thread_messages=thread_messages
        )
        if not context:
            post_thread_reply(
                bot_token=cfg.slack_bot_token,
                channel=channel,
                thread_ts=thread_ts,
                message=_NO_CONTENT_MESSAGE,
            )
            return

        file_path = _publish_test_plan(context, channel, thread_ts, cfg)
        logger.info("Test plan saved to %s", file_path)
    except Exception as exc:
        logger.exception("Failed to process app_mention")
        logger.error("Failed to process app_mention: %s", exc)
        msg = str(exc).strip() or type(exc).__name__
        if len(msg) > 300:
            msg = msg[:297] + "..."
        try:
            post_thread_reply(
                bot_token=cfg.slack_bot_token,
                channel=channel,
                thread_ts=thread_ts,
                message=f"❌ Failed to generate test plan: {msg}",
            )
        except Exception:
            logger.exception("Could not post failure message to Slack")
