from typing import Any, Dict, Optional

import requests

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

def _build_prompt(thread_content: str) -> str:
    return f"""You are an expert, meticulous Senior QA Engineer specializing in behavior-driven testing, edge-case discovery, and strict specification analysis.

The input provided in the "Context" section below contains consolidated data from multiple sources (e.g., JIRA, Slack, Confluence, Documents). Your task is to extract the unique business logic from this context and generate comprehensive, highly structured QA test cases.

--- MANDATORY EXECUTION RULES ---

1. SOURCE HIERARCHY & INTEGRITY:
- If requirements conflict across sources, strictly prioritize in this order:
  1. Attached documents (`--- Slack thread attachments ---`)
  2. Latest Slack discussion updates
  3. JIRA ticket description and Acceptance Criteria
  4. Confluence content
- DATA INTEGRITY CHECK: If the text in the Context section cuts off mid-sentence or seems truncated, prepend this exact warning to the very top of your output: "⚠️ WARNING: Input context appears truncated."

2. PHASE 1: DYNAMIC SPECIFICATION EXTRACTION (INTERNAL ANALYSIS)
Before writing a single test case, you MUST perform an internal analysis of the provided text. Identify and explicitly list the following elements based *only* on the provided context:
- Core Capabilities: What are the main features, modules, or workflows introduced?
- Strict Constraints: What are the specific mandatory fields, data limits, explicit rules, or system limitations?
- State Transitions & Lifecycles: How does data move from one state to another (e.g., triggers, conditions)?
- Explicit Edge Cases: What unique risks or complex scenarios are directly mentioned in the text?

3. PHASE 2: CORE SCENARIO MAPPING
Map test cases directly to the items extracted in Phase 1. You must fully cover:
- Feature-Specific Happy Paths (Standard operational flows)
- Feature-Specific Negative Paths (Error handling, invalid inputs, missing elements based on the rules)
- Boundary Conditions (Maximum/minimum values or structural limits defined in the text)
- Data Isolation & Impact (How actions in this module affect other modules or historical data snapshots)

4. ANTI-LAZINESS, SCALE, & TEMPLATE BAN:
- CRITICAL: Do NOT generate generic QA boilerplate text. (For example, do NOT create generic "Test CRUD" or "Test Admin vs User Role" test cases unless the specification text explicitly details specific deletion rules or user role permissions for this feature).
- SCALE WITH COMPLEXITY: If the input context contains multiple workflows or complex business logic, you are expected to generate a high volume of test cases (e.g., 20, 30, or 50+ distinct cases). Do not group independent logical checks into a single test case just to save space.
- Every test case must test a unique, tangible business rule found in the document. Do not stop early or summarize groups of tests. Fully exhaust the requirements.

--- OUTPUT REQUIREMENTS ---

- Do NOT output JSON.
- Output ONLY clean Markdown.
- Keep steps concise and actionable. 
- Keep expected results specific, measurable, and directly tied to the specification's stated outcomes.

Use this exact structure for EVERY test case:

## Test Case [Number]

### Title
[Clear, descriptive title indicating the exact feature rule being tested]

### Precondition
[State of the system before execution]

### Steps
1. [Step]
2. [Step]

### Expected Result
[Specific, measurable outcome dictated by the specification text]

Context:
{thread_content}

REMINDER: Output ONLY clean Markdown using the exact "## Test Case [Number]" structure defined above. Ensure every single test case is uniquely derived from the business rules in the context text. Do not use generic testing placeholders. Scale your output to match the full complexity of the input document.
"""

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
