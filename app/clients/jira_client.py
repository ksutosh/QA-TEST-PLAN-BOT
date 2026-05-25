import re
from typing import Any, Dict, List, Optional

import requests

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_JIRA_ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
_JIRA_BROWSE_URL_RE = re.compile(
    r"https?://[^\s<>|]+?/(?:jira/)?browse/([A-Z][A-Z0-9]+-\d+)(?:[/?#]|$|\|)",
    re.IGNORECASE,
)


def extract_issue_key(*texts: str) -> Optional[str]:
    """Extract a JIRA issue key from plain text or Atlassian browse URLs."""
    for text in texts:
        if not text:
            continue
        url_match = _JIRA_BROWSE_URL_RE.search(text)
        if url_match:
            return url_match.group(1).upper()
        key_match = _JIRA_ISSUE_KEY_RE.search(text)
        if key_match:
            return key_match.group(1)
    return None


def _adf_to_plain_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_plain_text(item) for item in node)
    if not isinstance(node, dict):
        return ""

    if node.get("type") == "text":
        return node.get("text") or ""

    parts: List[str] = []
    for child in node.get("content") or []:
        part = _adf_to_plain_text(child)
        if part:
            parts.append(part)
    block_type = node.get("type")
    if block_type in {"paragraph", "heading", "listItem", "bulletList", "orderedList"}:
        return "\n".join(parts) + "\n"
    return "".join(parts)


def _format_jira_issue(issue: Dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    key = issue.get("key") or ""
    summary = (fields.get("summary") or "").strip()
    description = fields.get("description")

    if isinstance(description, dict):
        desc_text = _adf_to_plain_text(description).strip()
    elif description:
        desc_text = str(description).strip()
    else:
        desc_text = ""

    lines = [f"JIRA Issue: {key}"]
    if summary:
        lines.append(f"Summary: {summary}")
    if desc_text:
        lines.append(f"Description:\n{desc_text}")
    return "\n".join(lines).strip()


def fetch_issue_details(issue_id: str, settings: Optional[Settings] = None) -> Dict:
    """Fetch issue details from JIRA REST API v3."""
    cfg = settings or get_settings()
    if not cfg.jira_api_base or not cfg.jira_email or not cfg.jira_api_token:
        raise RuntimeError("JIRA is not configured (JIRA_API_BASE, JIRA_EMAIL, JIRA_API_TOKEN)")

    url = f"{cfg.jira_api_base}/{issue_id}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = requests.get(
        url,
        auth=(cfg.jira_email, cfg.jira_api_token),
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()
    logger.info("JIRA issue details fetched successfully for %s", issue_id)
    return data


def fetch_jira_context(issue_key: str, settings: Optional[Settings] = None) -> Optional[str]:
    """Fetch and format a JIRA issue for use in the test-plan prompt."""
    try:
        issue = fetch_issue_details(issue_key, settings=settings)
        return _format_jira_issue(issue)
    except Exception as exc:
        logger.warning("Could not fetch JIRA issue %s: %s", issue_key, exc)
        return None


def combine_jira_and_slack(
    jira_content: Optional[str],
    slack_content: Optional[str],
) -> str:
    """Merge JIRA and Slack sources into a single prompt body."""
    parts: List[str] = []
    if jira_content:
        parts.append("--- JIRA ---\n" + jira_content)
    if slack_content:
        parts.append("--- Slack thread ---\n" + slack_content)
    return "\n\n".join(parts).strip()
