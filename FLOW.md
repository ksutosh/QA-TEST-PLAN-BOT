# Testplanbot — architecture and end-to-end flow

Structured reference for how the Slack QA Test Plan Bot works: events, context gathering, LLM, outputs, configuration, and operations.

---

## Table of contents

1. [Overview](#1-overview)
2. [High-level architecture](#2-high-level-architecture)
3. [End-to-end sequence](#3-end-to-end-sequence)
4. [Slack integration](#4-slack-integration)
5. [Context gathering](#5-context-gathering)
6. [LLM test plan generation](#6-llm-test-plan-generation)
7. [Publishing outputs](#7-publishing-outputs)
8. [Project structure and file reference](#8-project-structure-and-file-reference)
9. [Environment variables](#9-environment-variables)
10. [Local development (ngrok)](#10-local-development-ngrok)
11. [Logging and troubleshooting](#11-logging-and-troubleshooting)
12. [Design decisions](#12-design-decisions)

---

## 1. Overview

### What it does

When a user **@mentions the bot** in a Slack channel or thread, the service:

1. Acknowledges the event immediately (Slack 3-second rule).
2. Loads the **full thread** (messages + file attachments).
3. Builds a **merged context** from all detected sources.
4. Calls **Groq** to produce a Markdown test plan (≥10 cases).
5. Saves **`output/test_plan_<timestamp>.html`**.
6. Creates a **new Confluence page** (if configured).
7. **Replies in the same thread** with success or error.

### Dynamic Slack targeting

Channel and thread come from **each event** — nothing is hardcoded:

```python
channel = event.get("channel")
thread_ts = event.get("thread_ts") or event.get("ts")
```

| Field | Meaning |
|-------|---------|
| `channel` | Channel (or DM) where the mention happened |
| `thread_ts` | Parent timestamp if mention is inside a thread |
| `ts` | Fallback: mention on a top-level message → that message is the thread root |

---

## 2. High-level architecture

```text
┌─────────────┐     HTTPS POST      ┌──────────────────┐
│   Slack     │ ──────────────────► │  FastAPI         │
│ Events API  │   /slack/events     │  app/api/        │
└─────────────┘                     │  slack_events    │
                                    └────────┬─────────┘
                                             │ BackgroundTasks
                                             ▼
                                    ┌──────────────────┐
                                    │ test_plan_       │
                                    │ pipeline         │
                                    └────────┬─────────┘
                         ┌───────────────────┼───────────────────┐
                         ▼                   ▼                   ▼
                  slack_client        context_resolver      llm_client
                  (thread + files)    (merge sections)      (Groq)
                         │                   │
                         │         ┌─────────┼─────────┐
                         │         ▼         ▼         ▼
                         │    attachments  jira/    confluence
                         │                 slack
                         ▼
                  confluence_client + formatter
                         │
                         ▼
                  Slack reply (same channel + thread_ts)
```

### Layer responsibilities

| Layer | Path | Role |
|-------|------|------|
| API | `app/api/slack_events.py` | Slack webhook, url_verification, enqueue work |
| Pipeline | `app/services/test_plan_pipeline.py` | Orchestrate fetch → context → publish |
| Context | `app/services/context_*.py` | Build labeled prompt sections |
| Clients | `app/clients/*.py` | External APIs (Slack, JIRA, Confluence, Groq) |
| Core | `app/core/` | Settings, logging |
| Utils | `app/utils/` | File text extraction, HTML save |

---

## 3. End-to-end sequence

```text
User @mentions bot in channel/thread
        │
        ▼
POST /slack/events  (type: event_callback, event.type: app_mention)
        │
        ├── url_verification (setup only) → return { "challenge": "..." }
        │
        └── Return 200 { "ok": true } immediately
                    │
                    ▼  [background: process_app_mention_event]
        │
        ├─ channel, thread_ts from event
        │
        ├─ conversations.replies → raw messages[]
        │
        ├─ clean_and_combine_thread → slack_text
        │
        ├─ resolve_context(mention_text, slack_text, messages)
        │     ├─ (1) --- Slack thread attachments ---  [if files extracted]
        │     ├─ (2) --- JIRA --- / --- Slack thread ---
        │     └─ (3) --- Confluence page ---            [if wiki link found]
        │
        ├─ generate_test_plan_markdown(merged context)  → Groq
        │
        ├─ markdown → HTML
        │
        ├─ save_html_file → output/test_plan_*.html
        │
        ├─ create_confluence_page (if configured)
        │
        └─ chat.postMessage → "✅ Test plan created: <path>" or error
```

---

## 4. Slack integration

### App configuration

| Setting | Value |
|---------|--------|
| Request URL | `https://<host>/slack/events` |
| Bot event | `app_mention` |
| Scopes | `conversations:history`, `chat:write`, `files:read` |

### Event handler (`app/api/slack_events.py`)

1. Parse JSON payload.
2. `url_verification` → echo `challenge`.
3. Ignore non-`event_callback` payloads.
4. Ignore if `event.type != app_mention` or `event.bot_id` is set.
5. `background_tasks.add_task(process_app_mention_event, event)`.
6. Return `{"ok": true}` without waiting for LLM/Confluence.

### Thread messages (`slack_client.py`)

- **`fetch_thread_messages`** — `conversations.replies` with `channel` + `ts=thread_ts`.
- **`clean_and_combine_thread`** — filters noise:
  - Empty text
  - Pure `@mention` lines
  - Short triggers (`ok`, `done`, mention-only)
- **`post_thread_reply`** — `chat.postMessage` with same `channel` + `thread_ts`.

### Thread file attachments (`slack_client.py` + `file_text.py`)

Files appear on message objects under `files[]` in `conversations.replies`.

| Step | Function | Behavior |
|------|----------|----------|
| Collect | `collect_thread_files` | Dedupe by file `id` across thread |
| Metadata | `files.info` | If `url_private` missing in reply payload |
| Download | GET `url_private_download` with bot token | Stream with size cap |
| Extract | `extract_text_from_bytes` | Text, MD, PDF (`pypdf`), DOCX (`python-docx`), HTML |

Skipped types: images, video, audio, zip (see `_SKIP_FILETYPES`).

Logs to watch:

```text
Found N unique file attachment(s) in thread
Extracted text from Slack file <name> (X chars)
Attachment in prompt: <name> (X chars)
Context section slack_attachments: X chars
```

If attachments are skipped: check `files:read`, file format, or `SLACK_MAX_ATTACHMENT_BYTES`.

---

## 5. Context gathering

### Resolver (`context_resolver.py`)

**`resolve_context`** merges sections in this **order** (intentional for LLM focus):

| Order | Section header | Builder | Trigger |
|-------|----------------|---------|---------|
| 1 | `--- Slack thread attachments ---` | `context_slack_files.py` | Any extractable upload in thread |
| 2 | `--- JIRA ---` / `--- Slack thread ---` | `context_jira_slack.py` | Issue key/URL and/or thread text |
| 3 | `--- Confluence page ---` | `context_confluence.py` | Wiki `/pages/{id}` URL in mention or thread |

Empty merge → pipeline posts `_NO_CONTENT_MESSAGE` (no JIRA, Confluence, files, or thread text).

### JIRA (`jira_client.py` + `context_jira_slack.py`)

- **Not** webhook-based; pulled when user mentions bot.
- **`extract_issue_key`**: browse URL first, then pattern `PROJ-123` in thread or mention text.
- **`fetch_jira_context`**: REST GET issue → summary + description (ADF → plain text).
- Failure → warning log; pipeline continues if Slack text or attachments exist.

### Confluence context (`confluence_client.py` + `context_confluence.py`)

- **`extract_confluence_url`** — finds first wiki page URL.
- **`fetch_confluence_page_body`** — GET page with `body-format=storage`, convert HTML to plain text via `html_text.py`.

### Confluence publish (`confluence_client.create_confluence_page`)

Separate from context fetch: always creates a **new** page under configured `SPACE_ID` / `PARENT_ID` with `CONFLUENCE_TITLE` (static today; dynamic title from JIRA is a planned improvement).

---

## 6. LLM test plan generation

### Client (`llm_client.py`)

- **API:** `https://api.groq.com/openai/v1/chat/completions`
- **Default model:** `llama-3.3-70b-versatile` (override with `GROQ_MODEL`)
- **Parameters:** `temperature=0.2`, `max_tokens=8192`

### Prompt rules (summary)

The user prompt defines a **Senior QA Engineer** role with:

**Mandatory execution**

1. If `--- Slack thread attachments ---` has data → **required** multiple test cases from that document (not optional).
2. **Source hierarchy** on conflict:
   1. Attachments (primary spec)
   2. Latest Slack thread updates
   3. JIRA description & acceptance criteria
   4. Confluence page content
3. Coverage: positive/negative, edge, validation, cross-module, regression where applicable.
4. Ignore greetings, bot mentions, footers, boilerplate.

**Output**

- ≥10 test cases, Markdown only (no JSON).
- Structure per case: `## Test Case [N]`, Title, Precondition, Steps, Expected Result.

Full prompt text lives in `_build_prompt()` in `llm_client.py`.

---

## 7. Publishing outputs

### Local HTML (`formatter.py`)

- Path: `output/test_plan_<YYYYMMDD_HHMMSS>.html`
- Content: Markdown test plan rendered to HTML via Python `markdown` library.

### Confluence page

- POST to Confluence Cloud REST API v2 pages endpoint (`CONFLUENCE_API_BASE`).
- Auth: email + API token (HTTP basic).
- Body: same HTML as local file (`representation: storage`).

### Slack reply

Success:

```text
✅ Test plan created: /absolute/path/to/output/test_plan_....html
```

Failure: truncated error message (max ~300 chars).

---

## 8. Project structure and file reference

### `app/main.py`

- `create_app()` — FastAPI + lifespan + `/health` + Slack router.

### `main.py` (repo root)

- Re-exports `app` for `uvicorn main:app`.

### `app/api/slack_events.py`

- `POST /slack/events` only.

### `app/services/test_plan_pipeline.py`

| Function | Purpose |
|----------|---------|
| `process_app_mention_event` | Main coordinator |
| `_publish_test_plan` | Groq → HTML → Confluence → Slack reply |

### `app/services/context_resolver.py`

- `resolve_context` — merge sections, log char counts per section.

### `app/services/context_slack_files.py`

- `build_slack_files_context` — download + format attachment block.

### `app/services/context_jira_slack.py`

- `build_jira_slack_context` — JIRA + cleaned thread text.

### `app/services/context_confluence.py`

- `build_confluence_context` — linked page as plain text.

### `app/clients/slack_client.py`

| Function | Purpose |
|----------|---------|
| `fetch_thread_messages` | Thread history |
| `clean_and_combine_thread` | Filtered text blob |
| `collect_thread_files` | Unique attachments |
| `download_thread_file_texts` | Download + extract |
| `post_thread_reply` | Thread reply |

### `app/clients/jira_client.py`

| Function | Purpose |
|----------|---------|
| `extract_issue_key` | Key or URL from text |
| `fetch_jira_context` | Formatted issue for prompt |
| `combine_jira_and_slack` | Labeled merge |

### `app/clients/confluence_client.py`

| Function | Purpose |
|----------|---------|
| `extract_confluence_url` | Find wiki link |
| `fetch_confluence_page_body` | GET page for context |
| `create_confluence_page` | POST new page |

### `app/clients/llm_client.py`

| Function | Purpose |
|----------|---------|
| `_build_prompt` | Full QA instructions + context |
| `generate_test_plan_markdown` | Groq call |

### `app/utils/file_text.py`

- `extract_text_from_bytes` — text/PDF/DOCX/HTML extraction and truncation.

### `app/utils/html_text.py`

- `html_storage_to_plain_text` — Confluence storage HTML → plain text.

### `app/utils/formatter.py`

- `save_html_file` — timestamped HTML under `output/`.

### `app/core/config.py`

- `Settings` (Pydantic) + `get_settings()` from `.env`.

### `app/core/logging.py`

- `setup_logging`, `get_logger` → `logs/app.log` + console.

### Non-code paths

| Path | Purpose |
|------|---------|
| `.env` | Secrets (**do not commit**) |
| `.env.example` | Template |
| `output/` | Generated HTML |
| `logs/app.log` | Runtime logs |
| `venv/` | Local virtualenv |

---

## 9. Environment variables

| Variable | Required | Used for |
|----------|----------|----------|
| `SLACK_BOT_TOKEN` | Yes | Slack API |
| `GROQ_API_KEY` | Yes | Groq LLM |
| `GROQ_MODEL` | No | Model override |
| `JIRA_API_BASE` | No | JIRA issue fetch |
| `JIRA_EMAIL` | No | JIRA basic auth |
| `JIRA_API_TOKEN` | No | JIRA basic auth |
| `CONFLUENCE_API_BASE` | No | Confluence GET/POST |
| `CONFLUENCE_EMAIL` | No | Confluence auth |
| `CONFLUENCE_API_TOKEN` | No | Confluence auth |
| `SPACE_ID` | No | New page space |
| `PARENT_ID` | No | New page parent |
| `CONFLUENCE_TITLE` | No | New page title |
| `OUTPUT_DIR` | No | Local HTML directory |
| `LOG_LEVEL` | No | Logging |
| `SLACK_MAX_ATTACHMENT_BYTES` | No | Max file download size |
| `SLACK_MAX_ATTACHMENT_CHARS` | No | Max text per file in prompt |

---

## 10. Local development (ngrok)

Slack must reach your app over **public HTTPS**. Local `uvicorn` alone is not enough.

```bash
uvicorn main:app --reload
# In another terminal:
ngrok http 8000
```

Set Slack **Event Subscriptions → Request URL** to:

```text
https://<your-subdomain>.ngrok-free.app/slack/events
```

ngrok is a dev tunnel, not a code dependency. Production: deploy to a host with a stable URL (Railway, Render, VM, etc.).

---

## 11. Logging and troubleshooting

### Where logs go

- `logs/app.log` and stdout
- Startup: JIRA/Confluence configured or not

### Healthy run (checklist)

| Log line | Meaning |
|----------|---------|
| `Processing app_mention channel=... thread_ts=...` | Event received |
| `conversations.replies returned N messages` | Thread loaded |
| `Found N unique file attachment(s)` | Files seen on messages |
| `Extracted text from Slack file ...` | Document in prompt |
| `Context section slack_attachments: X chars` | Attachment section size |
| `Context section jira_slack: Y chars` | JIRA/thread section size |
| `Resolved context: N section(s), total Z chars` | Ready for Groq |
| `Test plan saved to ...` | Success |

### Common issues

| Symptom | Likely cause |
|---------|----------------|
| No Slack events | ngrok down, wrong Request URL, app not running |
| `not_in_channel` | Bot not invited to private channel |
| `files:read` / no download URL | Missing scope or reinstall app |
| Document ignored in tests but logs show extraction | LLM focus — prompt now mandates attachment cases; retry after restart |
| `0 unique file attachment(s)` | File not in same thread or uploaded after fetch |
| Confluence 4xx | Wrong `SPACE_ID`/`PARENT_ID`/API base or token |
| Groq error | Invalid `GROQ_MODEL` or API key |

### Verify attachment pipeline

```bash
grep -E "attachment|Extracted text|Context section" logs/app.log | tail -20
```

---

## 12. Design decisions

1. **Fast Slack ack** — `BackgroundTasks` so JIRA + Groq + Confluence do not time out Slack retries.
2. **Dynamic `channel` / `thread_ts`** — multi-channel without config changes.
3. **Attachments first in merged context** — primary spec before JIRA/thread/Confluence.
4. **Prompt hierarchy** — attachments rank #1; explicit requirement to generate cases from `--- Slack thread attachments ---`.
5. **JIRA pull model** — no JIRA webhook; keys/URLs from Slack text only.
6. **Resilient optional sources** — JIRA/Confluence/attachment failures degrade gracefully when other sections exist.
7. **Single-tenant `.env`** — one set of credentials today; multi-user/hosted would need per-user storage (see prior architecture discussion).

---

## Related documentation

- [README.md](README.md) — setup, scopes, quick start.

This document must not contain real tokens or `.env` secrets.
