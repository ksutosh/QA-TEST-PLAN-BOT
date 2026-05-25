# Slack QA Test Plan Bot

A FastAPI service that listens for Slack `@mentions`, gathers requirements from **thread uploads**, **JIRA**, **Confluence links**, and **Slack discussion**, generates a structured test plan with **Groq**, saves local HTML, publishes a **Confluence** page, and replies in the same thread.

For full architecture and flow, see **[FLOW.md](FLOW.md)**.

---

## Features

- **`app_mention`** handling with fast Slack ack + background processing
- **Dynamic channel/thread** from each Slack event (no hardcoded channel ID)
- **Multi-source context**: attachments → JIRA + Slack → Confluence
- **Thread documents**: `.md`, `.txt`, `.pdf`, `.docx`, HTML, and other text-like files
- **JIRA**: issue key or browse URL in mention or thread
- **Confluence**: wiki `/pages/{id}` link → page body as context; new page on publish
- **Structured LLM output**: ≥10 Markdown test cases with mandatory attachment coverage rules

---

## Project layout

```text
Testplanbot/
├── app/
│   ├── api/
│   │   └── slack_events.py       # POST /slack/events
│   ├── clients/
│   │   ├── slack_client.py       # Thread, files, replies
│   │   ├── jira_client.py
│   │   ├── confluence_client.py
│   │   └── llm_client.py         # Groq + QA prompt
│   ├── core/
│   │   ├── config.py             # Settings (Pydantic + .env)
│   │   └── logging.py
│   ├── services/
│   │   ├── test_plan_pipeline.py # Orchestrator
│   │   ├── context_resolver.py   # Merges all context sections
│   │   ├── context_slack_files.py
│   │   ├── context_jira_slack.py
│   │   └── context_confluence.py
│   ├── utils/
│   │   ├── file_text.py          # PDF/DOCX/text extraction
│   │   ├── html_text.py          # Confluence HTML → plain text
│   │   └── formatter.py          # output/test_plan_*.html
│   └── main.py                   # App factory, /health
├── main.py                       # uvicorn main:app entry
├── output/                       # Generated HTML (gitignored)
├── logs/app.log
├── requirements.txt
├── .env.example
├── FLOW.md
└── README.md
```

---

## Quick start

### 1. Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure `.env`

Copy `.env.example` to `.env` and fill in values.

**Required**

| Variable | Description |
|----------|-------------|
| `SLACK_BOT_TOKEN` | Bot User OAuth Token (`xoxb-...`) |
| `GROQ_API_KEY` | Groq API key |

**Optional — JIRA**

| Variable | Description |
|----------|-------------|
| `JIRA_API_BASE` | e.g. `https://your-site.atlassian.net/rest/api/3/issue` |
| `JIRA_EMAIL` | Atlassian account email |
| `JIRA_API_TOKEN` | Atlassian API token |

**Optional — Confluence (publish + link fetch)**

| Variable | Description |
|----------|-------------|
| `CONFLUENCE_API_BASE` | v2 pages API base (see FLOW.md) |
| `CONFLUENCE_EMAIL` | Atlassian email |
| `CONFLUENCE_API_TOKEN` | API token |
| `SPACE_ID` | Target space ID |
| `PARENT_ID` | Parent page ID for new pages |
| `CONFLUENCE_TITLE` | Default title for created pages |

**Optional — tuning**

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model ID |
| `OUTPUT_DIR` | `output` | Local HTML output folder |
| `LOG_LEVEL` | `INFO` | Logging level |
| `SLACK_MAX_ATTACHMENT_BYTES` | `5000000` | Max download size per file |
| `SLACK_MAX_ATTACHMENT_CHARS` | `80000` | Max extracted text per file |

### 3. Slack app setup

1. Create a Slack app and install it to your workspace.
2. **OAuth scopes (Bot Token):**
   - `conversations:history` — read thread messages
   - `chat:write` — post replies
   - `files:read` — download thread uploads
3. **Event Subscriptions:** enable events, set Request URL to  
   `https://<your-public-host>/slack/events`
4. Subscribe to bot event: **`app_mention`**
5. Invite the bot to channels: `/invite @YourBot`

For local dev, expose the app with **ngrok** (or similar) — see [FLOW.md § Local development](FLOW.md#6-local-development-ngrok).

### 4. Run

```bash
uvicorn app.main:app --reload
# or
uvicorn main:app --reload
```

Health check: `GET http://localhost:8000/health`

---

## Usage

1. Start a Slack thread with requirements (discussion, JIRA key/link, Confluence link, uploaded spec).
2. `@mention` the bot in that thread.
3. The bot replies with the local HTML path when done, or an error / “no content” message.

**Example inputs (any combination)**

- JIRA: `SCRUM-5` or `https://your-site.atlassian.net/browse/SCRUM-5`
- Confluence: `https://your-site.atlassian.net/wiki/spaces/TEAM/pages/123456/...`
- Document: upload `.md`, `.txt`, `.pdf`, `.docx` in the thread
- Slack: thread messages with feature discussion

---

## Logs

- File: `logs/app.log`
- Useful lines after a run:
  - `Found N unique file attachment(s) in thread`
  - `Extracted text from Slack file ...`
  - `Context section slack_attachments: X chars`
  - `Resolved context: N section(s), total Y chars`

```bash
LOG_LEVEL=DEBUG uvicorn main:app --reload
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [FLOW.md](FLOW.md) | End-to-end flow, context merge order, LLM rules, file reference, troubleshooting |

---

## Security

- Do **not** commit `.env` (see `.gitignore`).
- Rotate tokens if they were ever pushed to git.
- Production: use HTTPS, validate Slack signing secret (future hardening), host on a always-on service.
