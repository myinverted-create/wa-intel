#!/usr/bin/env python3
"""
Fetch the daily WA commercial construction recruitment brief from Grok (xAI),
parse the JSON response, and write it to data/latest.json + data/history/<date>.json.

Required env vars:
  XAI_API_KEY   — your xAI API key (set as a GitHub Actions secret)

Optional env vars:
  XAI_MODEL     — defaults to "grok-4-latest". Override if xAI renames models.
"""

import os
import sys
import json
import glob
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
PROMPT_PATH = REPO_ROOT / "prompts" / "daily_brief.md"
WATCHLIST_PATH = DATA_DIR / "watchlist.json"

XAI_API_KEY = os.environ.get("XAI_API_KEY")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4-latest")
XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"

AWST = timezone(timedelta(hours=8))


def load_prompt() -> str:
    template = PROMPT_PATH.read_text()
    watchlist = json.loads(WATCHLIST_PATH.read_text())["builders"]
    rendered = "\n".join(f"  - {b}" for b in watchlist)
    today = datetime.now(AWST).strftime("%Y-%m-%d")
    return template.replace("{{WATCHLIST}}", rendered).replace("YYYY-MM-DD", today)


def call_grok(prompt: str) -> dict:
    if not XAI_API_KEY:
        raise SystemExit("XAI_API_KEY env var is not set. Add it as a GitHub Actions secret.")

    payload = {
        "model": XAI_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise data-returning assistant. Always return valid JSON exactly matching the requested schema. No prose."},
            {"role": "user", "content": prompt},
        ],
        # xAI live search — pulls fresh web + news + X data into the response
        "search_parameters": {
            "mode": "on",
            "return_citations": True,
            "sources": [
                {"type": "web"},
                {"type": "news"},
                {"type": "x"}
            ]
        },
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    resp = requests.post(
        XAI_ENDPOINT,
        headers={
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    resp.raise_for_status()
    body = resp.json()

    content = body["choices"][0]["message"]["content"]
    # Some models occasionally wrap JSON in ```json fences despite response_format.
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    return json.loads(content)


def save(brief: dict) -> str:
    today_dt = datetime.now(AWST)
    today = today_dt.strftime("%Y-%m-%d")
    brief["date"] = today
    brief["generated_at"] = today_dt.isoformat()

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    (DATA_DIR / "latest.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False))
    (HISTORY_DIR / f"{today}.json").write_text(json.dumps(brief, indent=2, ensure_ascii=False))

    # Rebuild history index
    dates = sorted(
        [Path(f).stem for f in glob.glob(str(HISTORY_DIR / "*.json"))],
        reverse=True,
    )
    (DATA_DIR / "history-index.json").write_text(
        json.dumps({"dates": dates}, indent=2)
    )

    return today


def main() -> None:
    print("Loading prompt + watchlist...", flush=True)
    prompt = load_prompt()

    print(f"Calling Grok ({XAI_MODEL})...", flush=True)
    try:
        brief = call_grok(prompt)
    except requests.HTTPError as e:
        print(f"xAI HTTP error: {e.response.status_code}\n{e.response.text}", file=sys.stderr)
        raise

    print("Saving brief...", flush=True)
    today = save(brief)
    print(f"Done. Brief for {today} written.")


if __name__ == "__main__":
    main()
