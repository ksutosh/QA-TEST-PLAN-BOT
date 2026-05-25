import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)


def _clean(value: Optional[str]) -> Optional[str]:
    """Strip whitespace and optional surrounding quotes from .env values."""
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    return cleaned or None


def _require(name: str) -> str:
    value = _clean(os.getenv(name))
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


class Settings(BaseModel):
    slack_bot_token: str
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    jira_api_base: Optional[str] = None
    jira_email: Optional[str] = None
    jira_api_token: Optional[str] = None

    confluence_api_base: Optional[str] = None
    confluence_email: Optional[str] = None
    confluence_api_token: Optional[str] = None
    space_id: Optional[str] = None
    parent_id: Optional[str] = None
    confluence_title: Optional[str] = None

    output_dir: str = "output"
    log_level: str = "INFO"
    slack_max_attachment_bytes: int = 5_000_000
    slack_max_attachment_chars: int = 80_000

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            slack_bot_token=_require("SLACK_BOT_TOKEN"),
            groq_api_key=_require("GROQ_API_KEY"),
            groq_model=_clean(os.getenv("GROQ_MODEL")) or "llama-3.3-70b-versatile",
            jira_api_base=_clean(os.getenv("JIRA_API_BASE")),
            jira_email=_clean(os.getenv("JIRA_EMAIL")),
            jira_api_token=_clean(os.getenv("JIRA_API_TOKEN")),
            confluence_api_base=_clean(os.getenv("CONFLUENCE_API_BASE")),
            confluence_email=_clean(os.getenv("CONFLUENCE_EMAIL")),
            confluence_api_token=_clean(os.getenv("CONFLUENCE_API_TOKEN")),
            space_id=_clean(os.getenv("SPACE_ID")),
            parent_id=_clean(os.getenv("PARENT_ID")),
            confluence_title=_clean(os.getenv("CONFLUENCE_TITLE")),
            output_dir=_clean(os.getenv("OUTPUT_DIR")) or "output",
            log_level=_clean(os.getenv("LOG_LEVEL")) or "INFO",
            slack_max_attachment_bytes=int(
                _clean(os.getenv("SLACK_MAX_ATTACHMENT_BYTES")) or 5_000_000
            ),
            slack_max_attachment_chars=int(
                _clean(os.getenv("SLACK_MAX_ATTACHMENT_CHARS")) or 80_000
            ),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.load()
