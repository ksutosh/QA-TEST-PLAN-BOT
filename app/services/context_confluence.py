from typing import Optional

from app.clients.confluence_client import extract_confluence_url, fetch_confluence_page_body
from app.core.config import Settings
from app.core.logging import get_logger
from app.utils.html_text import html_storage_to_plain_text

logger = get_logger(__name__)


def build_confluence_context(
    mention_text: str,
    slack_text: str,
    settings: Settings,
) -> Optional[str]:
    """Build prompt context from a Confluence wiki link in mention or thread."""
    page_url = extract_confluence_url(mention_text, slack_text)
    if not page_url:
        return None

    logger.info("Found Confluence page URL: %s", page_url)
    html_body = fetch_confluence_page_body(page_url, settings=settings)
    plain_text = html_storage_to_plain_text(html_body)
    if not plain_text:
        logger.warning("Confluence page %s had no extractable text", page_url)
        plain_text = "(empty page body)"

    return f"--- Confluence page ---\nSource: {page_url}\n\n{plain_text}"
