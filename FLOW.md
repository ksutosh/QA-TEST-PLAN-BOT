# Testplanbot — end-to-end flow and architecture

This document describes how the **Slack QA Test Plan Bot** works: from a Slack mention through **JIRA** and **Slack** context gathering, LLM generation, local HTML output, **Confluence** publishing, and the final Slack reply. It also explains **why tools like ngrok** are typically used (ngrok is not in the source code; it is a dev-time tunnel).

---

## What the project does (one sentence)

When someone **mentions the bot in a Slack thread**, the app gathers context from a **Confluence wiki link**, **JIRA issue**, and/or **Slack thread** (any combination), turns it into a **structured QA test plan** using **Groq**, saves an **HTML** snapshot under `output/`, creates a **new Confluence page**, and posts a **confirmation (or error) in the same thread**.

---

## What each file contains

### `app/main.py`

- **FastAPI application** factory (`create_app`) and **`lifespan`** (logging + settings validation on startup).
- **`GET /health`** — returns `{"status": "ok"}`.
- Mounts **`app/api/slack_events.py`** router.

### `main.py` (repo root)

- Re-exports **`app`** for `uvicorn main:app` compatibility.

### `app/api/slack_events.py`

- **`POST /slack/events`** — Slack Events API handler:
  - Handles `url_verification` (returns `challenge`).
  - Ignores non-`app_mention` events and events with `bot_id`.
  - Reads `event` from payload as a dict (no strict schema required).
  - Enqueues **`process_app_mention_event`** as a background task and returns `200` immediately.

### `app/services/test_plan_pipeline.py`

- **`process_app_mention_event`** — coordinator: Slack thread → **`resolve_context`** → **`_publish_test_plan`**.
- **`_publish_test_plan`** — shared output path (Groq → HTML file → new Confluence page → Slack reply).

### `app/services/context_resolver.py`

- **`resolve_context`** — merges all detected sources:
  1. Confluence section (if wiki `/pages/{id}` link in mention or thread).
  2. JIRA + Slack section (if issue key and/or thread text).

### `app/services/context_confluence.py`

- **`build_confluence_context`** — fetch page storage HTML, convert to plain text, label as `--- Confluence page ---`.

### `app/services/context_jira_slack.py`

- **`build_jira_slack_context`** — JIRA fetch + `combine_jira_and_slack` (original workflow).

### `app/utils/html_text.py`

- **`html_storage_to_plain_text`** — strips Confluence storage HTML for the LLM prompt.

### `app/clients/slack_client.py`

- Constants: `SLACK_API_BASE`, `NOISE_MESSAGES` (`ok`, `done`).
- **`fetch_thread_messages`**, **`clean_and_combine_thread`**, **`post_thread_reply`**.

### `app/clients/jira_client.py`

- JIRA REST + **`extract_issue_key`**, ADF parsing, **`combine_jira_and_slack`**.
- Uses **`Settings`** from `app/core/config.py`.

### `app/clients/llm_client.py`

- Groq chat completions and **`generate_test_plan_markdown`**.

### `app/clients/confluence_client.py`

- **`extract_confluence_url`**, **`extract_confluence_page_id`**, **`fetch_confluence_page_body`** (GET `{api}/pages/{id}?body-format=storage`).
- **`create_confluence_page`** — POST new page (same v2 pages API base).

### `app/utils/formatter.py`

- **`save_html_file`** — writes `output/test_plan_<timestamp>.html`.

### `app/core/config.py`

- **`Settings`** (Pydantic) — central env validation for Slack, Groq, JIRA, Confluence.
- **`get_settings()`** — cached singleton.

### `app/core/logging.py`

- **`setup_logging`**, **`get_logger`** — `logs/app.log` + console.

### `requirements.txt`

- Dependencies: `fastapi`, `uvicorn`, `requests`, `python-dotenv`, `Markdown>=3.5`.

### Other paths (not application modules)

| Path | Purpose |
|------|---------|
| `.env` | Secrets and service URLs (Slack, Groq, JIRA, Confluence). **Do not commit.** |
| `output/` | Generated HTML test plans (`test_plan_*.html`). |
| `logs/app.log` | Runtime application logs. |
| `README.md` | Quick setup and run instructions. |
| `FLOW.md` | This architecture and flow document. |
| `venv/` | Local Python virtual environment (not part of app logic). |

---

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `SLACK_BOT_TOKEN` | `app/core/config.py`, clients, pipeline | Bot OAuth token for Slack Web API |
| `GROQ_API_KEY` | `app/core/config.py`, `llm_client.py` | Groq API authentication |
| `GROQ_MODEL` | `app/core/config.py`, `llm_client.py` | Optional model override |
| `JIRA_API_BASE` | `app/core/config.py`, `jira_client.py` | Base URL for issue fetch |
| `JIRA_EMAIL` | `app/core/config.py`, `jira_client.py` | Atlassian account email for basic auth |
| `JIRA_API_TOKEN` | `app/core/config.py`, `jira_client.py` | Atlassian API token |
| `CONFLUENCE_API_BASE` | `app/core/config.py`, `confluence_client.py` | Confluence v2 pages create endpoint URL |
| `CONFLUENCE_EMAIL` | `app/core/config.py`, `confluence_client.py` | Confluence basic auth email |
| `CONFLUENCE_API_TOKEN` | `app/core/config.py`, `confluence_client.py` | Confluence API token |
| `SPACE_ID` | `app/core/config.py`, `confluence_client.py` | Target Confluence space ID |
| `PARENT_ID` | `app/core/config.py`, `confluence_client.py` | Parent page ID for new pages |
| `CONFLUENCE_TITLE` | `app/core/config.py`, `confluence_client.py` | Page title for new Confluence pages |

---

## Why ngrok (or a similar tunnel) is used

**Slack’s Events API** sends HTTP `POST` requests from Slack’s servers to your app’s **Request URL**. That URL must be:

- **Publicly reachable** from the internet (Slack cannot call `http://localhost:...` on your laptop).
- Often **HTTPS** (Slack’s configuration expects a secure endpoint in production-like setups).

When you run the bot locally with:

```bash
uvicorn main:app --reload
```

the server binds to your machine only. **ngrok**, **Cloudflare Tunnel**, **localtunnel**, or deploying to a real host exposes `http://localhost:8000` as a **public URL** for Slack’s **Event Subscriptions → Request URL** (e.g. `https://<subdomain>.ngrok-free.app/slack/events`).

ngrok is a **development convenience**, not a Python dependency: the app only needs a public route to `POST /slack/events`.

---

## Slack → app wiring

1. Create a Slack app with scopes: **`conversations:history`**, **`chat:write`**.
2. **Event Subscriptions**: Request URL → `https://<your-public-host>/slack/events`.
3. Subscribe to bot event: **`app_mention`**.
4. Install app → set **`SLACK_BOT_TOKEN`** in `.env`.
5. Invite the bot to the channel (`/invite @YourBot`).

---

## JIRA integration (how it fits in)

The bot does **not** listen to JIRA webhooks. JIRA is used as an **optional context source** when the user triggers the bot from Slack.

### How a JIRA issue is detected

`extract_issue_key` scans, in order, across the cleaned **Slack thread text** and the **`app_mention` message text**:

1. **Browse URL** — e.g. `https://testplanbot.atlassian.net/browse/SCRUM-5`
2. **Issue key** — e.g. `SCRUM-5` (pattern: uppercase project key + hyphen + number)

### What is fetched from JIRA

If a key is found, `fetch_jira_context` calls JIRA REST API v3:

- **Summary** and **description** (description converted from ADF to plain text when needed)
- Formatted as a labeled block for the LLM

If JIRA fetch fails (network, auth, missing issue), the bot **logs a warning** and continues with Slack-only content if the thread has text.

### Minimum content rule

After merging, if **both** JIRA and Slack yield nothing useful, the bot replies:

> No content found. Include a JIRA issue key (e.g. SCRUM-5), a browse link, or Slack thread context.

### Typical usage patterns

| Pattern | What the LLM sees |
|---------|-------------------|
| Mention + JIRA key/link only | `--- JIRA ---` section |
| Mention in a thread with discussion | `--- JIRA ---` + `--- Slack thread ---` |
| Thread only (no JIRA key) | `--- Slack thread ---` |

---

## HTTP entrypoints (`main.py`)

### `GET /health`

Returns `{"status": "ok"}`.

### `POST /slack/events`

1. Parse JSON; invalid → `400`.
2. **`url_verification`** → return `{"challenge": "..."}`.
3. **`event_callback`** → if not `app_mention` or has `bot_id`, return `{"ok": true}`.
4. Otherwise enqueue background processing and return **`200 {"ok": true}`** immediately.

**Why background tasks:** Slack expects a fast ack (~3s). JIRA fetch, Groq, file I/O, and Confluence can take longer.

---

## Processing an `app_mention` (step-by-step)

1. **Resolve** `channel`, `thread_ts` (`thread_ts` or root `ts`).
2. **Validate** `SLACK_BOT_TOKEN`, `GROQ_API_KEY`.
3. **Slack thread** — `fetch_thread_messages` → `clean_and_combine_thread` → `slack_text`.
4. **JIRA** — `extract_issue_key(slack_text, mention_text)` → if key, `fetch_jira_context`.
5. **Combine** — `combine_jira_and_slack(jira_text, slack_text)`; abort with helpful Slack message if empty.
6. **LLM** — `generate_test_plan_markdown` → Markdown test cases.
7. **HTML** — `markdown.markdown` → HTML fragment.
8. **Local file** — `save_html_file` → `output/test_plan_*.html`.
9. **Confluence** — `create_confluence_page(html_content)`.
10. **Slack reply** — success with file path, or error message (truncated if long).

---

## End-to-end sequence

```text
User @mentions bot (optionally with SCRUM-5 or JIRA browse URL)
        │
        ▼
Slack POST /slack/events (event_callback, app_mention)
        │
        ├── url_verification (one-time): return challenge
        │
        └── FastAPI returns 200 {ok: true} quickly
                    │
                    ▼ (background)
        conversations.replies → clean thread → slack_text
                    │
                    ├── extract_issue_key(thread + mention)
                    │         │
                    │         ▼ (if key found)
                    │   JIRA REST GET issue → summary + description
                    │
                    ▼
        combine_jira_and_slack → single prompt body
                    │
                    ▼
        Groq chat completions → Markdown test plan
                    │
                    ▼
        markdown.markdown → HTML fragment
                    │
                    ├── save_html_file → output/test_plan_*.html
                    │
                    ├── create_confluence_page → new Confluence page
                    │
                    └── chat.postMessage → thread reply with path / error
```

---

## Logging

All modules use `get_logger(__name__)`. Logs go to **`logs/app.log`** and stdout via `app/core/logging.py`.

---

## How to run

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Point Slack’s Request URL at **`/slack/events`** on your public host (ngrok URL in local dev).

---

## Design choices

1. **Slack ack vs. heavy work** — background tasks avoid Slack timeouts and duplicate deliveries.
2. **JIRA as pull, not push** — no JIRA webhook setup; issue context is resolved from what the user typed in Slack.
3. **Resilient JIRA fetch** — failure does not crash the job if Slack thread text exists.
4. **Dual input for issue key** — thread history and the mention line are both scanned (key in mention or earlier thread message).
5. **ADF parsing** — JIRA Cloud descriptions often use Atlassian Document Format; converted to plain text for Groq.
6. **Tunnel (ngrok)** — local dev only; production should use a stable HTTPS deployment and secret management.

---

## Related docs

- `README.md` — setup, env vars, run command, Slack endpoint path.

This file is descriptive only and must not contain real tokens or `.env` secrets.
