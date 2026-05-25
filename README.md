# Slack QA Test Plan Bot (FastAPI)

This project listens to Slack `app_mention` events, reads the full thread (including uploaded documents), gathers context from Confluence/JIRA/links, sends content to Groq, writes a test plan HTML file, publishes to Confluence, and replies in the same Slack thread.

## Project layout

```text
app/
├── core/           # Settings (Pydantic) and logging
├── api/            # FastAPI routers (Slack events)
├── services/
│   ├── test_plan_pipeline.py   # Coordinator + publish
│   ├── context_resolver.py     # Merges Confluence + Jira/Slack sections
│   ├── context_confluence.py
│   ├── context_jira_slack.py
│   └── context_slack_files.py   # Thread uploads (.md, .txt, .pdf, .docx, …)
├── clients/        # Slack, Jira, Confluence, Groq
├── utils/          # HTML file output
└── main.py         # App factory and lifespan
main.py             # Re-exports app for uvicorn main:app
```

## Setup

1. Create and activate a virtual environment (recommended).
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Fill environment variables in `.env`:

   - `SLACK_BOT_TOKEN`
   - `GROQ_API_KEY`
   - Optional: JIRA and Confluence variables (see `FLOW.md`)

## Run

```bash
uvicorn app.main:app --reload
```

Or the compatibility entry point:

```bash
uvicorn main:app --reload
```

## Logs

- Runtime logs are stored at `logs/app.log`.
- Optional log level override:

  ```bash
  LOG_LEVEL=DEBUG uvicorn app.main:app --reload
  ```

## Slack Endpoint

Configure Slack Events API request URL to:

`http://<your-host>/slack/events`

**Bot token scopes:** `conversations:history`, `chat:write`, `files:read` (required to read `.md`, `.txt`, `.pdf`, `.docx`, and other uploads in the thread).

The app supports:
- Slack URL verification challenge
- `app_mention` event handling
- Thread file attachments (text, Markdown, PDF, DOCX, HTML, and other text-like files)
