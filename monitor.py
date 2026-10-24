#!/usr/bin/env python3
"""Poll an RSSHub X feed and deliver unseen posts to a Feishu custom bot."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import feedparser
import requests


ACCOUNT = os.environ.get("X_ACCOUNT", "YOUR_X_USERNAME").strip()
MAX_SEEN_IDS = 1000
REQUEST_TIMEOUT_SECONDS = 30
STATE_PATH = Path(__file__).with_name("state.json")

LOGGER = logging.getLogger(__name__)


class TextExtractor(HTMLParser):
    """Convert the HTML descriptions returned by RSS feeds into plain text."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return re.sub(r"[ \t]+", " ", unescape("".join(self.parts))).strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send-test",
        action="store_true",
        help="send a Feishu test card without fetching RSS or modifying state",
    )
    parser.add_argument(
        "--check-rss",
        action="store_true",
        help="validate RSS_URL without sending Feishu messages or modifying state",
    )
    return parser.parse_args()


def is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        LOGGER.info("State file does not exist; treating this as the first run.")
        return {"initialized": False, "seen_ids": []}

    try:
        with path.open(encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not load state file {path}: {error}") from error

    if not isinstance(state, dict) or not isinstance(state.get("seen_ids", []), list):
        raise RuntimeError(f"State file {path} has an invalid format.")

    return {
        "initialized": bool(state.get("initialized", False)),
        "seen_ids": [str(item) for item in state.get("seen_ids", [])],
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)


def fetch_feed(url: str) -> list[Any]:
    LOGGER.info("Fetching RSS feed: %s", url)
    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": "github-actions-x-feishu-monitor/1.0"},
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"RSS request failed: {error}") from error

    feed = feedparser.parse(response.content)
    if feed.bozo:
        LOGGER.warning("RSS parser warning: %s", feed.bozo_exception)
    if not getattr(feed, "entries", None):
        LOGGER.warning("RSS feed contains no entries.")
    return list(feed.entries)


def entry_id(entry: Any) -> str:
    identifier = entry.get("id") or entry.get("guid") or entry.get("link")
    if not identifier:
        raise ValueError("RSS entry has no id, guid, or link.")
    return str(identifier)


def entry_text(entry: Any) -> str:
    content = entry.get("content") or []
    content_text = content[0].get("value") if content and isinstance(content[0], dict) else ""
    raw_text = content_text or entry.get("summary") or entry.get("title") or ""
    parser = TextExtractor()
    parser.feed(str(raw_text))
    parser.close()
    return parser.get_text() or "(No text content)"


def is_repost(entry: Any) -> bool:
    title = str(entry.get("title", ""))
    text = entry_text(entry)
    return title.startswith("RT @") or text.startswith("RT @") or " retweeted " in title.lower()


def make_signature(timestamp: str, secret: str) -> str:
    digest = hmac.new(
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def trim_card_text(text: str) -> str:
    limit = 3500
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


def build_card(text: str, link: str, test: bool = False) -> dict[str, Any]:
    title = "X 监控测试消息" if test else f"@{ACCOUNT} 发布了新帖子"
    body = "这是一条飞书机器人连通性测试消息。" if test else trim_card_text(text)
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看原文"},
                            "type": "primary",
                            "url": link,
                        }
                    ],
                },
            ],
        },
    }


def send_feishu(card: dict[str, Any]) -> None:
    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    secret = os.environ.get("FEISHU_SIGNING_SECRET", "").strip()
    if not webhook:
        raise RuntimeError("FEISHU_WEBHOOK environment variable is not configured.")

    payload = card.copy()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = make_signature(timestamp, secret)

    try:
        response = requests.post(webhook, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RuntimeError(f"Feishu webhook request failed: {error}") from error

    try:
        result = response.json()
    except ValueError as error:
        raise RuntimeError("Feishu returned a non-JSON response.") from error

    if result.get("code", 0) != 0:
        raise RuntimeError(
            f"Feishu rejected the message (code={result.get('code')}, msg={result.get('msg')})."
        )


def run_monitor() -> None:
    state = load_state(STATE_PATH)
    entries = fetch_feed(configured_rss_url())
    observed_ids: list[str] = []
    valid_entries: list[tuple[str, Any]] = []

    for entry in entries:
        try:
            identifier = entry_id(entry)
        except ValueError as error:
            LOGGER.warning("Skipping malformed RSS entry: %s", error)
            continue
        observed_ids.append(identifier)
        valid_entries.append((identifier, entry))

    if not state["initialized"]:
        state["initialized"] = True
        state["seen_ids"] = list(dict.fromkeys(observed_ids))[:MAX_SEEN_IDS]
        save_state(STATE_PATH, state)
        LOGGER.info("Initial run: recorded %d existing posts without notification.", len(observed_ids))
        return

    seen_ids = set(state["seen_ids"])
    new_entries = [(identifier, entry) for identifier, entry in valid_entries if identifier not in seen_ids]
    if not new_entries:
        LOGGER.info("No new posts found.")
        return

    filter_reposts = is_truthy(os.environ.get("FILTER_RETWEETS", "true"))
    processed_count = 0
    for identifier, entry in reversed(new_entries):
        if filter_reposts and is_repost(entry):
            LOGGER.info("Ignoring repost: %s", identifier)
        else:
            link = str(entry.get("link") or f"https://x.com/{ACCOUNT}")
            LOGGER.info("Sending new post to Feishu: %s", link)
            send_feishu(build_card(entry_text(entry), link))

        # Persist after each item. If a later webhook call fails, a retry will
        # only contain items that have not already been acknowledged.
        state["seen_ids"] = list(dict.fromkeys([identifier] + state["seen_ids"]))[:MAX_SEEN_IDS]
        save_state(STATE_PATH, state)
        processed_count += 1

    LOGGER.info("Processed %d new post(s).", processed_count)


def configured_rss_url() -> str:
    rss_url = os.environ.get("RSS_URL", "").strip()
    if not rss_url:
        raise RuntimeError(
            "RSS_URL is not configured. Set it in .github/workflows/x-monitor.yml, "
            "for example http://127.0.0.1:1200/twitter/user/YOUR_X_USERNAME."
        )
    return rss_url


def check_rss() -> None:
    entries = fetch_feed(configured_rss_url())
    LOGGER.info("RSS feed is reachable and parsed successfully; found %d item(s).", len(entries))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    try:
        if args.send_test:
            send_feishu(build_card("", f"https://x.com/{ACCOUNT}", test=True))
            LOGGER.info("Feishu test card sent successfully.")
        elif args.check_rss:
            check_rss()
        else:
            run_monitor()
    except Exception as error:
        LOGGER.error("Monitor failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
