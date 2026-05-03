"""
fpl_probe_agents.py -- two Claude agents that work in tandem to surface
unhandled intents in the FPL grounded assistant.

Architecture:
  Orchestrator (this script)
    +- Agent 1 - Questioner  -> generates the next realistic Spanish FPL question
    +- Agent 2 - Evaluator   -> analyses the API response and decides whether
                               to write a catalog entry or mark it as PASS

Usage:
    python scripts/fpl_probe_agents.py --base-url https://fpl-backend-production-4151.up.railway.app/
    python scripts/fpl_probe_agents.py --base-url http://localhost:8000 --rounds 20
    python scripts/fpl_probe_agents.py --dry-run
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import textwrap
from pathlib import Path

import time

import anthropic
import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PACKAGE_ROOT / "UNHANDLED_INTENTS_CATALOG.md"

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"  # fast + cheap for structured generation
DEFAULT_ROUNDS = 30

KNOWN_CATEGORIES = [
    "Captain / Vice-Captain",
    "Transfer Planning",
    "Player Pick / Start Recommendation",
    "Fixture Difficulty / Schedule Analysis",
    "Player Info / Stats",
    "Chip Strategy",
    "Squad / Bench Management",
    "Gameweek Info",
    "Meta / App Behavior",
    "Other / Uncategorized",
]

KNOWN_INTENTS = [
    "captain_score", "rank_candidates", "current_gameweek", "player_summary",
    "player_resolve", "compare_players", "transfer_advice", "chip_advice",
    "player_fixture_run", "differential_picks", "unsupported",
]

PRIORITY_MAP = {
    "Captain / Vice-Captain": "P1",
    "Transfer Planning": "P1",
    "Player Pick / Start Recommendation": "P1",
    "Fixture Difficulty / Schedule Analysis": "P1",
    "Player Info / Stats": "P1",
    "Chip Strategy": "P2",
    "Squad / Bench Management": "P2",
    "Gameweek Info": "P2",
    "Meta / App Behavior": "P3",
}

SECTION_HEADERS = {cat: f"## Category: {cat}" for cat in KNOWN_CATEGORIES}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Two-agent FPL probe: question generator + response evaluator.")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p.add_argument("--timeout", type=int, default=25)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--anthropic-api-key", default=None)
    return p.parse_args()


# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

def make_client(api_key: str | None) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def llm_call(client: anthropic.Anthropic, system: str, prompt: str, max_tokens: int = 1024) -> str:
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"  [LLM error] {str(e)[:120]}")
        return ""


# ---------------------------------------------------------------------------
# Read already-catalogued prompts
# ---------------------------------------------------------------------------

def existing_prompts(catalog: Path) -> list[str]:
    if not catalog.exists():
        return []
    text = catalog.read_text(encoding="utf-8")
    return re.findall(r'\*\*Raw prompt:\*\* "([^"]+)"', text)


# ---------------------------------------------------------------------------
# FPL API call
# ---------------------------------------------------------------------------

def call_fpl_api(base_url: str, question: str, timeout: int) -> dict:
    url = f"{base_url.rstrip('/')}/ask"
    try:
        r = httpx.post(url, json={"question": question}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {
            "error": str(e),
            "final_text": "",
            "supported": False,
            "intent": "connection_error",
            "outcome": "connection_error",
        }


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    """Pull first JSON object out of a text that may include markdown fences."""
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Agent 1 -- Questioner
# ---------------------------------------------------------------------------

QUESTIONER_SYSTEM = textwrap.dedent("""
    You are an FPL (Fantasy Premier League) expert stress-testing a Spanish-language FPL chat assistant.
    Your job: generate ONE realistic Spanish FPL question that a real manager would type in a chat app.

    Rules:
    - Write naturally in Spanish, the way someone would actually type at 2am before a deadline.
    - Do NOT repeat questions that have already been asked.
    - Target categories and angles that have not been explored yet.
    - Focus especially on questions the assistant cannot currently handle well.

    The assistant handles these intents (examples of what works):
    - captain_score: "deberia capitar a haaland?"
    - rank_candidates: "quien es el mejor capitan esta semana?"
    - current_gameweek: "en que jornada estamos?"
    - player_summary: "dame info de salah" (returns price/ownership only, NOT match history)
    - player_resolve: "quien es kdb?"
    - compare_players: "compara a salah y haaland"
    - transfer_advice: "deberia vender a saka y fichar a palmer?"
    - chip_advice: "uso el wildcard?"
    - player_fixture_run: "dame los fixtures de haaland"
    - differential_picks: "dame diferenciales"

    Return ONLY a JSON object, no other text:
    {
      "question": "<the raw Spanish question>",
      "category": "<one of the category list>",
      "notes": "<one sentence: what user need does this represent?>",
      "expected_intent": "<intent name or 'unknown'>"
    }

    Valid categories: Captain / Vice-Captain, Transfer Planning, Player Pick / Start Recommendation,
    Fixture Difficulty / Schedule Analysis, Player Info / Stats, Chip Strategy,
    Squad / Bench Management, Gameweek Info, Meta / App Behavior, Other / Uncategorized
""").strip()


def run_questioner(client: anthropic.Anthropic, asked: list[str], found_gaps: list[str]) -> dict | None:
    gaps_text = "\n".join(f"  - {g}" for g in found_gaps[-15:]) if found_gaps else "  (none yet)"
    asked_text = "\n".join(f'  - "{q}"' for q in asked[-20:]) if asked else "  (none yet)"

    prompt = (
        f"Already asked (do not repeat):\n{asked_text}\n\n"
        f"Gaps found so far (target new territory):\n{gaps_text}\n\n"
        f"Generate the next question now."
    )
    raw = llm_call(client, QUESTIONER_SYSTEM, prompt, max_tokens=256)
    return extract_json(raw)


# ---------------------------------------------------------------------------
# Agent 2 -- Evaluator
# ---------------------------------------------------------------------------

EVALUATOR_SYSTEM = textwrap.dedent("""
    You are a QA reviewer for a Spanish-language FPL (Fantasy Premier League) chat assistant.
    You receive a question and the assistant's full JSON response.

    Decide:
    - PASS: the response is complete, correct, and genuinely useful to an FPL manager.
    - CATALOG: the response has a problem.

    Problems that qualify as CATALOG (be strict):
    - supported=false or outcome contains "unsupported"
    - Response in wrong language (e.g. Portuguese for a Spanish question)
    - Name parsing error (e.g. Spanish preposition "a" absorbed into player name)
    - Response only returns price/ownership when the user asked for match stats or form
    - Response is a polite refusal or vague fallback
    - Response is missing key data the question asked for
    - Wrong intent matched (e.g. question about last 5 games routed to player_summary)

    Return ONLY a JSON object:

    For PASS:
    {
      "verdict": "PASS",
      "reason": "<why this is a good response>"
    }

    For CATALOG:
    {
      "verdict": "CATALOG",
      "app_response_description": "<one line: what went wrong>",
      "user_need": "<one sentence: what the user actually wanted>",
      "priority": "P1" | "P2" | "P3",
      "category": "<category name>",
      "technical_notes": "<optional: root cause, intent matched, missing data, etc.>"
    }

    Priority: P1=core FPL decision asked constantly, P2=legitimate niche question, P3=out of MVP scope.
    Valid categories: Captain / Vice-Captain, Transfer Planning, Player Pick / Start Recommendation,
    Fixture Difficulty / Schedule Analysis, Player Info / Stats, Chip Strategy,
    Squad / Bench Management, Gameweek Info, Meta / App Behavior, Other / Uncategorized
""").strip()


def run_evaluator(client: anthropic.Anthropic, question: str, q_meta: dict, fpl_response: dict) -> dict | None:
    response_summary = json.dumps({
        "supported": fpl_response.get("supported"),
        "intent": fpl_response.get("intent"),
        "outcome": fpl_response.get("outcome"),
        "llm_used": fpl_response.get("llm_used"),
        "final_text": fpl_response.get("final_text", "")[:500],
        "error": fpl_response.get("error"),
    }, ensure_ascii=False, indent=2)

    prompt = (
        f'Question: "{question}"\n'
        f"Category hint: {q_meta.get('category', 'unknown')}\n"
        f"User need: {q_meta.get('notes', '')}\n\n"
        f"API response:\n{response_summary}"
    )
    raw = llm_call(client, EVALUATOR_SYSTEM, prompt, max_tokens=512)
    return extract_json(raw)


# ---------------------------------------------------------------------------
# Write a single entry to the catalog
# ---------------------------------------------------------------------------

def append_entry(catalog: Path, entry: dict, question: str, intent_got: str) -> None:
    text = catalog.read_text(encoding="utf-8") if catalog.exists() else ""
    date = datetime.date.today().isoformat()
    category = entry.get("category", "Other / Uncategorized")
    header = SECTION_HEADERS.get(category, f"## Category: {category}")
    priority = entry.get("priority", PRIORITY_MAP.get(category, "P2"))
    label = entry.get("user_need", question)[:60]
    technical = entry.get("technical_notes", "")

    md_entry = (
        f"\n### {label}\n"
        f'- **Raw prompt:** "{question}"\n'
        f"- **App response:** {entry['app_response_description']}\n"
        f"- **User need:** {entry['user_need']}\n"
        f"- **Priority:** {priority}\n"
        f"- **Source:** fpl_probe_agents automated scan, {date}\n"
    )
    if technical:
        md_entry += f"- **Notes:** {technical} (intent=`{intent_got}`)\n"

    if header in text:
        text = text.replace(header, header + md_entry, 1)
    else:
        fallback = "## Category: Other / Uncategorized"
        block = f"\n---\n\n{header}\n{md_entry}"
        if fallback in text:
            text = text.replace(fallback, block + "\n\n" + fallback, 1)
        else:
            text += "\n" + block

    catalog.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()

    client = make_client(args.anthropic_api_key)

    already_catalogued = existing_prompts(CATALOG_PATH)
    asked: list[str] = list(already_catalogued)
    found_gaps: list[str] = list(already_catalogued)

    print(f"FPL API   : {args.base_url}")
    print(f"Model     : {ANTHROPIC_MODEL}")
    print(f"Rounds    : {args.rounds}")
    print(f"Dry run   : {args.dry_run}")
    print(f"Pre-known : {len(already_catalogued)} catalogued prompts loaded")
    print()

    try:
        r = httpx.get(f"{args.base_url.rstrip('/')}/ready", timeout=5)
        if r.status_code != 200:
            print(f"[WARN] /ready -> {r.status_code} -- bootstrap may not be loaded\n")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Cannot reach {args.base_url}: {e}\n")

    catalogued_count = 0
    pass_count = 0

    for i in range(1, args.rounds + 1):
        print(f"-- Round {i}/{args.rounds} {'-' * 40}")

        # Agent 1: generate question
        print("  [Questioner] generating...")
        q_meta = run_questioner(client, asked, found_gaps)
        if not q_meta or not q_meta.get("question"):
            print("  [Questioner] failed to produce a question -- skipping")
            time.sleep(5)
            continue

        question = q_meta["question"]
        print(f'  [Q] "{question}"')
        print(f"      category={q_meta.get('category')} | expected={q_meta.get('expected_intent', '?')}")

        if question in asked:
            print("  [Questioner] duplicate -- skipping")
            continue
        asked.append(question)

        # Fire at FPL API
        fpl_resp = call_fpl_api(args.base_url, question, args.timeout)
        intent_got = fpl_resp.get("intent", "n/a")
        supported = fpl_resp.get("supported", False)
        final_text = fpl_resp.get("final_text", "")[:120]
        print(f"  [API] intent={intent_got} supported={supported}")
        print(f'        -> "{final_text}"')

        # Agent 2: evaluate
        print("  [Evaluator] analysing...")
        verdict = run_evaluator(client, question, q_meta, fpl_resp)

        if verdict is None:
            print("  [Evaluator] could not parse verdict -- skipping")
            continue

        if verdict.get("verdict") == "PASS":
            pass_count += 1
            print(f"  [Evaluator] PASS -- {verdict.get('reason', '')[:80]}")
        else:
            catalogued_count += 1
            gap_summary = f"{question[:60]} ({verdict.get('app_response_description', '')[:40]})"
            found_gaps.append(gap_summary)
            desc = verdict.get("app_response_description", "")
            print(f"  [Evaluator] CATALOG -- {desc[:80]}")
            if args.dry_run:
                print(f'  [DRY RUN] would write entry for: "{question}"')
            else:
                append_entry(CATALOG_PATH, verdict, question, intent_got)
                print(f"  [Catalog] written -> {CATALOG_PATH.name}")

        print()

    print("=" * 60)
    print(f"Done. Rounds={args.rounds}  PASS={pass_count}  CATALOGUED={catalogued_count}")
    if not args.dry_run and catalogued_count:
        print(f"Findings written to {CATALOG_PATH}")


if __name__ == "__main__":
    main()
