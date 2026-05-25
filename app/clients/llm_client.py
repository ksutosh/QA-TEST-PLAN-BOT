from typing import Any, Dict, Optional

import requests

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def _build_prompt(thread_content: str) -> str:
    return f"""
You are a senior QA engineer.

The input below may contain multiple sources of information including:

- Slack discussion thread
- JIRA ticket details
- Confluence page content
- Attached document contents (.txt, .md, .docx, .pdf, etc.)
- User clarifications and follow-up discussions

Your task:
Analyze all available context and generate practical, structured QA test cases.

Rules:
- Prioritize explicit requirements over assumptions.
- Use discussion comments to identify edge cases and clarifications.
- Use attached documents if present and extract requirements from them.
- Ignore irrelevant content such as:
  - greetings
  - bot mentions
  - page footers
  - file metadata
  - boilerplate text
  - generated timestamps
  - duplicate content
- If multiple sources contain conflicting requirements, prefer:
    1. Explicit latest discussion updates
    2. JIRA requirements
    3. Attached documents
- Include:
    - Positive scenarios
    - Negative scenarios
    - Edge cases
    - Validation scenarios
    - Cross-module impacts if mentioned
    - Regression scenarios if applicable

Requirements:
- Generate at least 5 test cases
- Generate more if complexity requires it
- Do NOT output JSON
- Use clean Markdown formatting
- Keep steps concise and actionable
- Keep expected results specific and measurable

Use this exact structure:

## Test Case 1

### Title
...

### Precondition
...

### Steps
1.
2.

### Expected Result
...

Context:
{thread_content}
""".strip()


def generate_test_plan_markdown(
    thread_content: str,
    groq_api_key: Optional[str] = None,
    settings: Optional[Settings] = None,
    timeout_seconds: int = 60,
) -> str:
    """Send cleaned thread content to Groq and return markdown test plan."""
    cfg = settings or get_settings()
    api_key = groq_api_key or cfg.groq_api_key
    model = (cfg.groq_model or DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
    logger.info("Using model: %s", model)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert software QA engineer who writes practical, "
                    "structured markdown test plans."
                ),
            },
            {
                "role": "user",
                "content": _build_prompt(thread_content),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
    }

    response = requests.post(
        GROQ_CHAT_COMPLETIONS_URL,
        headers=headers,
        json=payload,
        timeout=timeout_seconds,
    )
    logger.info("Groq API response: %s", response.json())
    if not response.ok:
        detail = response.text.strip() or response.reason
        raise RuntimeError(
            f"Groq API error {response.status_code}: {detail}. "
            f"If this mentions an unknown model, set GROQ_MODEL to a current ID "
            f"(e.g. llama-3.3-70b-versatile or llama-3.1-8b-instant)."
        )
    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Unexpected Groq response format") from exc

    if not content or not content.strip():
        raise RuntimeError("Groq returned an empty test plan")

    return content.strip()
