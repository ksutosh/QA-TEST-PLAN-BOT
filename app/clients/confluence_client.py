import re
from typing import Optional

import requests

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_CONFLUENCE_PAGE_URL_RE = re.compile(
    r"https?://[^\s<>|\"']+/wiki/[^\s<>|\"']*?/pages/(\d+)[^\s<>|\"']*",
    re.IGNORECASE,
)
_CONFLUENCE_PAGE_ID_RE = re.compile(r"/pages/(\d+)")


def extract_confluence_page_id(page_url: str) -> Optional[str]:
    """Extract the numerical page ID from a Confluence Cloud wiki or API URL."""
    match = _CONFLUENCE_PAGE_ID_RE.search(page_url)
    if match:
        logger.info("Extracted Confluence page ID: %s", match.group(1))
        return match.group(1)
    return None


def extract_confluence_url(*texts: str) -> Optional[str]:
    """Find the first Confluence wiki page URL in the given texts."""
    for text in texts:
        if not text:
            continue
        match = _CONFLUENCE_PAGE_URL_RE.search(text)
        if match:
            return match.group(0)
    return None


def _pages_api_base(cfg: Settings) -> str:
    """Normalize CONFLUENCE_API_BASE to the v2 pages collection URL."""
    base = (cfg.confluence_api_base or "").rstrip("/")
    if not base:
        raise RuntimeError("CONFLUENCE_API_BASE is not configured")
    if base.endswith("/pages"):
        return base
    if base.endswith("/content"):
        return base[: -len("/content")] + "/pages"
    return base + "/pages" if "/pages" not in base else base


def fetch_confluence_page_body(page_url: str, settings: Optional[Settings] = None) -> str:
    """Fetch page body (storage HTML) by wiki URL via Confluence REST API v2."""
    cfg = settings or get_settings()
    if not cfg.confluence_email or not cfg.confluence_api_token:
        raise RuntimeError(
            "Confluence is not configured (CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)"
        )

    page_id = extract_confluence_page_id(page_url)
    if not page_id:
        raise ValueError(f"Could not extract page ID from Confluence URL: {page_url}")

    url = f"{_pages_api_base(cfg)}/{page_id}?body-format=storage"
    headers = {"Accept": "application/json"}
    response = requests.get(
        url,
        auth=(cfg.confluence_email, cfg.confluence_api_token),
        headers=headers,
        timeout=30,
    )

    if not response.ok:
        error_body = (response.text or "").strip() or "(empty response body)"
        if len(error_body) > 4000:
            error_body = error_body[:4000] + "... (truncated)"
        logger.error(
            "Confluence GET failed: status=%s page_id=%s url=%s body=%s",
            response.status_code,
            page_id,
            url,
            error_body,
        )
        raise RuntimeError(f"Failed to fetch Confluence page {page_id}: {error_body}")

    data = response.json()
    logger.info("Confluence page fetched successfully: id=%s", page_id)
    try:
        return data["body"]["storage"]["value"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("Unexpected Confluence page response format") from exc


def create_confluence_page(content: str, settings: Optional[Settings] = None) -> bool:
    """Create a new Confluence page."""
    cfg = settings or get_settings()
    if not all(
        [
            cfg.confluence_api_base,
            cfg.confluence_email,
            cfg.confluence_api_token,
            cfg.space_id,
            cfg.parent_id,
            cfg.confluence_title,
        ]
    ):
        raise RuntimeError(
            "Confluence is not configured "
            "(CONFLUENCE_API_BASE, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, "
            "SPACE_ID, PARENT_ID, CONFLUENCE_TITLE)"
        )

    url = _pages_api_base(cfg)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = {
        "spaceId": cfg.space_id,
        "status": "current",
        "title": cfg.confluence_title,
        "parentId": cfg.parent_id,
        "body": {
            "representation": "storage",
            "value": content,
        },
        "subtype": "live",
    }
    response = requests.post(
        url,
        auth=(cfg.confluence_email, cfg.confluence_api_token),
        headers=headers,
        json=payload,
        timeout=30,
    )
    if not response.ok:
        error_body = (response.text or "").strip() or "(empty response body)"
        if len(error_body) > 4000:
            error_body = error_body[:4000] + "... (truncated)"
        logger.error(
            "Confluence API failed: status=%s reason=%s title=%s spaceId=%s parentId=%s body=%s",
            response.status_code,
            response.reason,
            cfg.confluence_title,
            cfg.space_id,
            cfg.parent_id,
            error_body,
        )
    response.raise_for_status()
    logger.info("Confluence page created successfully: %s", response.json())
    return True
