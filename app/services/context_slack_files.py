"""Build LLM context from files uploaded in a Slack thread."""

from typing import Any, Dict, List, Optional

from app.clients.slack_client import download_thread_file_texts
from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_slack_files_context(
    thread_messages: List[Dict[str, Any]],
    settings: Settings,
) -> Optional[str]:
    """
    Download and extract text from documents shared in the thread.

    Supports common text formats, PDF, DOCX, and HTML; unsupported binaries are skipped.
    """
    extracted = download_thread_file_texts(
        bot_token=settings.slack_bot_token,
        messages=thread_messages,
        max_bytes=settings.slack_max_attachment_bytes,
        max_chars_per_file=settings.slack_max_attachment_chars,
    )
    with_text = [item for item in extracted if item.get("text", "").strip()]
    if not with_text:
        skipped = sum(1 for item in extracted if item.get("skipped_reason"))
        if skipped:
            logger.info("Context: %s Slack attachment(s) skipped (no extractable text)", skipped)
        return None

    blocks: List[str] = []
    for item in with_text:
        blocks.append(f"### {item['name']}\n{item['text']}")

    body = "\n\n".join(blocks).strip()

    logger.info("Context: %s Slack attachment(s) with extractable text", len(with_text))
    return "--- Slack thread attachments ---\n" + body
