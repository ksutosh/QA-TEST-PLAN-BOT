from typing import Optional

from app.clients.jira_client import (
    combine_jira_and_slack,
    extract_issue_key,
    fetch_jira_context,
)
from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_jira_slack_context(
    mention_text: str,
    slack_text: str,
    settings: Settings,
) -> Optional[str]:
    """Build prompt context from JIRA issue (if linked) and Slack thread text."""
    issue_key = extract_issue_key(slack_text, mention_text)
    jira_text: Optional[str] = None
    if issue_key:
        logger.info("Found JIRA issue key: %s", issue_key)
        jira_text = fetch_jira_context(issue_key, settings=settings)

    combined = combine_jira_and_slack(jira_text, slack_text or None)
    return combined or None
