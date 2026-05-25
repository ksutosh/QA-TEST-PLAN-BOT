import re
from typing import Any, Dict, List, Optional, Set

import requests

from app.core.logging import get_logger
from app.utils.file_text import extract_text_from_bytes

logger = get_logger(__name__)

SLACK_API_BASE = "https://slack.com/api"
NOISE_MESSAGES = {"ok", "done"}

# Slack file types that are never useful as text context.
_SKIP_FILETYPES = frozenset(
    {"png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "mp4", "mov", "mp3", "wav", "zip", "gz"}
)


def fetch_thread_messages(
    bot_token: str,
    channel: str,
    thread_ts: str,
    timeout_seconds: int = 20,
) -> List[Dict]:
    """Fetch all messages in a Slack thread using conversations.replies."""
    logger.info("Fetching thread messages for channel=%s thread_ts=%s", channel, thread_ts)

    url = f"{SLACK_API_BASE}/conversations.replies"
    headers = {"Authorization": f"Bearer {bot_token}"}
    params = {"channel": channel, "ts": thread_ts}

    response = requests.get(url, headers=headers, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()
    logger.info("conversations.replies response: %s", data)

    if not data.get("ok"):
        err = data.get("error", "unknown_error")
        logger.error(
            "conversations.replies failed: %s (channel=%s ts=%s)", err, channel, thread_ts
        )
        raise RuntimeError(f"Slack conversations.replies error: {err}")

    messages = data.get("messages", [])
    logger.info("messages: %s", messages)
    logger.info("conversations.replies returned %s messages", len(messages))
    return messages


def _is_pure_mention(text: str) -> bool:
    return bool(re.fullmatch(r"\s*(<@[A-Z0-9]+>\s*)+\s*", text))


def _is_noise(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in NOISE_MESSAGES


def _is_short_trigger_message(text: str) -> bool:
    """Ignore bot trigger messages that contain only mention markup and no content."""
    mention_removed = re.sub(r"<@[A-Z0-9]+>", "", text)
    non_text = re.sub(r"[\s\W_]+", "", mention_removed)
    return not non_text


def clean_and_combine_thread(messages: List[Dict]) -> str:
    """Process Slack thread messages using filtering rules and combine messages."""
    cleaned_parts: List[str] = []
    for msg in messages:
        text = (msg.get("text") or "").strip()
        if not text:
            continue

        if _is_pure_mention(text):
            continue

        if _is_noise(text):
            continue

        if _is_short_trigger_message(text):
            continue

        cleaned_parts.append(text)

    return "\n".join(cleaned_parts).strip()


def collect_thread_files(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect unique file objects attached to messages in a thread."""
    seen: Set[str] = set()
    files: List[Dict[str, Any]] = []
    for msg in messages:
        for file_obj in msg.get("files") or []:
            file_id = file_obj.get("id")
            if not file_id or file_id in seen:
                continue
            seen.add(file_id)
            files.append(file_obj)
    return files


def _slack_api_get(
    bot_token: str,
    method: str,
    params: Optional[Dict[str, str]] = None,
    timeout_seconds: int = 20,
) -> Dict[str, Any]:
    url = f"{SLACK_API_BASE}/{method}"
    headers = {"Authorization": f"Bearer {bot_token}"}
    response = requests.get(
        url, headers=headers, params=params or {}, timeout=timeout_seconds
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack {method} error: {data.get('error', 'unknown_error')}")
    return data


def _resolve_file_metadata(
    bot_token: str, file_obj: Dict[str, Any], timeout_seconds: int = 20
) -> Dict[str, Any]:
    """Ensure we have url_private and size via files.info when the reply payload is sparse."""
    file_id = file_obj.get("id")
    if not file_id:
        return file_obj
    if file_obj.get("url_private") or file_obj.get("url_private_download"):
        return file_obj
    data = _slack_api_get(
        bot_token, "files.info", params={"file": file_id}, timeout_seconds=timeout_seconds
    )
    return data.get("file") or file_obj


def _download_file_bytes(
    bot_token: str,
    file_obj: Dict[str, Any],
    max_bytes: int,
    timeout_seconds: int = 60,
) -> tuple[Optional[bytes], Optional[str]]:
    """
    Download file content from Slack private URL.
    Returns (data, skip_reason). skip_reason is set when download is skipped or failed.
    """
    meta = _resolve_file_metadata(bot_token, file_obj, timeout_seconds=timeout_seconds)
    name = meta.get("name") or meta.get("title") or "attachment"
    filetype = (meta.get("filetype") or "").lower()
    mimetype = meta.get("mimetype") or ""
    size = meta.get("size") or 0

    if filetype in _SKIP_FILETYPES:
        return None, f"unsupported type ({filetype or mimetype})"

    if size and size > max_bytes:
        return None, f"file too large ({size} bytes, max {max_bytes})"

    url = meta.get("url_private_download") or meta.get("url_private")
    if not url:
        return None, "no download URL (check files:read scope)"

    headers = {"Authorization": f"Bearer {bot_token}"}
    response = requests.get(url, headers=headers, timeout=timeout_seconds, stream=True)
    response.raise_for_status()

    chunks: List[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return None, f"file too large (>{max_bytes} bytes)"
        chunks.append(chunk)

    return b"".join(chunks), None


def download_thread_file_texts(
    bot_token: str,
    messages: List[Dict[str, Any]],
    max_bytes: int = 5_000_000,
    max_chars_per_file: int = 80_000,
    timeout_seconds: int = 60,
) -> List[Dict[str, str]]:
    """
    Download thread attachments and extract plain text for the LLM.

    Each result dict has keys: name, text (optional), skipped_reason (optional).
    """
    file_list = collect_thread_files(messages)
    logger.info("Found %s unique file attachment(s) in thread", len(file_list))
    results: List[Dict[str, str]] = []
    for file_obj in file_list:
        try:
            meta = _resolve_file_metadata(
                bot_token, file_obj, timeout_seconds=timeout_seconds
            )
            name = meta.get("name") or meta.get("title") or meta.get("id") or "file"
            data, skip_reason = _download_file_bytes(
                bot_token,
                file_obj,
                max_bytes=max_bytes,
                timeout_seconds=timeout_seconds,
            )
            if skip_reason:
                logger.info("Skipping Slack file %s: %s", name, skip_reason)
                results.append({"name": name, "text": "", "skipped_reason": skip_reason})
                continue
            if not data:
                results.append(
                    {"name": name, "text": "", "skipped_reason": "empty file"}
                )
                continue

            text = extract_text_from_bytes(
                data,
                filename=name,
                mimetype=meta.get("mimetype"),
                max_chars=max_chars_per_file,
            )
            if text:
                logger.info("Extracted text from Slack file %s (%s chars)", name, len(text))
                results.append({"name": name, "text": text})
            else:
                logger.info("Could not extract text from Slack file %s", name)
                results.append(
                    {
                        "name": name,
                        "text": "",
                        "skipped_reason": "unsupported or unreadable format",
                    }
                )
        except Exception as exc:
            logger.warning("Failed to process Slack file %s: %s", name, exc)
            results.append(
                {"name": name, "text": "", "skipped_reason": f"download error: {exc}"}
            )

    return [r for r in results if r.get("text") or r.get("skipped_reason")]


def post_thread_reply(
    bot_token: str,
    channel: str,
    thread_ts: str,
    message: str,
    timeout_seconds: int = 20,
) -> Dict:
    """Post a reply in the same Slack thread."""
    url = f"{SLACK_API_BASE}/chat.postMessage"
    headers = {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "channel": channel,
        "text": message,
        "thread_ts": thread_ts,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage error: {data.get('error', 'unknown_error')}")

    return data
