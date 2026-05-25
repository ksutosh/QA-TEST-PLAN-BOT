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


def resolve_context(
    mention_text: str,
    slack_text: str,
    settings: Settings,
    thread_messages: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    Gather LLM prompt context from all detected sources.

    Policy: Confluence link body, thread file attachments, then JIRA + Slack text.
    """
    sections: List[str] = []

    confluence_ctx = build_confluence_context(mention_text, slack_text, settings)
    if confluence_ctx:
        sections.append(confluence_ctx)
        logger.info("Context: Confluence section added")

    if thread_messages:
        files_ctx = build_slack_files_context(thread_messages, settings)
        if files_ctx:
            sections.append(files_ctx)

    jira_slack_ctx = build_jira_slack_context(mention_text, slack_text, settings)
    if jira_slack_ctx:
        sections.append(jira_slack_ctx)
        logger.info("Context: JIRA/Slack section added")

    merged = _merge_sections(sections)
    if merged:
        logger.info("Resolved context length=%s chars", len(merged))
    return merged
