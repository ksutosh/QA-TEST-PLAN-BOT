from typing import Any, Dict, Optional

import requests

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


def _build_prompt(thread_content: str) -> str:
    return f"""You are an expert, meticulous Senior QA Engineer.

The input provided in the "Context" section below contains consolidated data from multiple sources:
- JIRA ticket details
- Slack discussion threads
- Confluence page content
- Attached document contents (.txt, .md, .docx, .pdf, etc.)

Your task is to analyze ALL available context and generate practical, structured QA test cases.

--- MANDATORY EXECUTION RULES ---
1. CRITICAL: You MUST check for the presence of the `--- Slack thread attachments ---` section. If this section contains data, you are REQUIRED to derive multiple test cases (covering core features, flows, and edge cases) directly from it. Do NOT treat this section as optional boilerplate.
2. SOURCE HIERARCHY: If requirements conflict across sources, you must strictly prioritize them in this order:
    1. Attached documents (`--- Slack thread attachments ---`) -> This is your primary specification.
    2. Explicit latest Slack thread updates -> For recent scope changes.
    3. JIRA ticket description & Acceptance Criteria.
    4. Confluence page content.
3. TESTING SCOPE: Ensure your test cases cover:
    - Positive and Negative scenarios
    - Edge cases and Validation scenarios
    - Cross-module impacts and Regression scenarios (if applicable)
4. CLEANUP: Ignore irrelevant content (greetings, bot mentions, page footers, duplicate boilerplate).

--- OUTPUT REQUIREMENTS ---
- Generate at least 10 test cases (more if complexity requires it).
- Do NOT output JSON. Output ONLY clean Markdown formatting.
- Keep steps concise and actionable.
- Keep expected results specific, objective, and measurable.

Use this exact structure for EVERY test case:

## Test Case [Number]

### Title
[Clear, descriptive title]

### Precondition
[State of the system before execution]

### Steps
1. [Step 1]
2. [Step 2]

### Expected Result
[Specific, measurable outcome]

---

Context:
{thread_content}"""


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
                    "You are an expert, meticulous Senior QA Engineer. You write practical, "
                    "structured markdown test plans and follow all mandatory execution rules."
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
