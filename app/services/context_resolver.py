from typing import Any, Dict, List, Optional

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.context_confluence import build_confluence_context
from app.services.context_jira_slack import build_jira_slack_context
from app.services.context_slack_files import build_slack_files_context

logger = get_logger(__name__)


def _merge_sections(sections: List[str]) -> Optional[str]:
    parts = [s.strip() for s in sections if s and s.strip()]
    if not parts:
        return None
    return "\n\n".join(parts)


def _log_section(label: str, content: str) -> None:
    logger.info("Context section %s: %s chars", label, len(content))


def resolve_context(
    mention_text: str,
    slack_text: str,
    settings: Settings,
    thread_messages: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Gather LLM prompt context from all detected sources.

    Order: attachments first (primary spec), then JIRA/Slack, then Confluence.
    """
    sections: List[str] = []

    if thread_messages:
        files_ctx = build_slack_files_context(thread_messages, settings)
        if files_ctx:
            sections.append(files_ctx)
            _log_section("slack_attachments", files_ctx)

    jira_slack_ctx = build_jira_slack_context(mention_text, slack_text, settings)
    if jira_slack_ctx:
        sections.append(jira_slack_ctx)
        _log_section("jira_slack", jira_slack_ctx)

    confluence_ctx = build_confluence_context(mention_text, slack_text, settings)
    if confluence_ctx:
        sections.append(confluence_ctx)
        _log_section("confluence", confluence_ctx)

    merged = _merge_sections(sections)
    if merged:
        logger.info(
            "Resolved context: %s section(s), total %s chars",
            len(sections),
            len(merged),
        )
    else:
        logger.warning("Resolved context is empty (no sections)")
    return merged
