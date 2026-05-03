"""
catalog_runner.py — fire every question in question_bank.py against the
FPL assistant API and append new findings to UNHANDLED_INTENTS_CATALOG.md.

Usage:
    python scripts/catalog_runner.py [--base-url http://localhost:8000]

The runner classifies each response into one of four buckets:
  PASS      — supported=True and intent matches expected (if set)
  BLOCKED   — supported=False
  MISMATCH  — supported=True but intent differs from expected_intent
  PARTIAL   — supported=True, intent matches, but response looks thin
              (heuristic: final_text under 120 chars)

Only BLOCKED, MISMATCH, and PARTIAL entries are written to the catalog.
Already-catalogued prompts (exact text match) are skipped automatically.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PACKAGE_ROOT / "UNHANDLED_INTENTS_CATALOG.md"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run FPL question bank against assistant API and catalog failures.")
    p.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the FPL assistant (default: http://localhost:8000)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout per request in seconds (default: 20)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print findings to stdout without writing to the catalog",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Load question bank
# ---------------------------------------------------------------------------

def load_questions() -> list[dict]:
    sys.path.insert(0, str(PACKAGE_ROOT / "scripts"))
    from question_bank import QUESTIONS  # noqa: PLC0415
    return QUESTIONS


# ---------------------------------------------------------------------------
# API call
# ---------------------------------------------------------------------------

def ask(base_url: str, question: str, timeout: int) -> dict:
    url = f"{base_url.rstrip('/')}/ask"
    try:
        resp = httpx.post(url, json={"question": question}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": str(e), "final_text": "", "supported": False, "intent": "error", "outcome": "http_error"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "final_text": "", "supported": False, "intent": "error", "outcome": "connection_error"}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

THIN_RESPONSE_CHARS = 120


def classify(q: dict, resp: dict) -> str:
    """Return PASS | BLOCKED | MISMATCH | PARTIAL."""
    if resp.get("error"):
        return "BLOCKED"
    supported = resp.get("supported", False)
    intent = resp.get("intent", "")
    final_text = resp.get("final_text", "")
    expected = q.get("expected_intent")

    if not supported:
        return "BLOCKED"
    if expected and intent != expected:
        return "MISMATCH"
    if len(final_text) < THIN_RESPONSE_CHARS:
        return "PARTIAL"
    return "PASS"


# ---------------------------------------------------------------------------
# Read existing catalog prompts to avoid duplicates
# ---------------------------------------------------------------------------

def existing_prompts(catalog: Path) -> set[str]:
    if not catalog.exists():
        return set()
    text = catalog.read_text(encoding="utf-8")
    # Extract everything inside **Raw prompt:** "..."
    return set(re.findall(r'\*\*Raw prompt:\*\* "([^"]+)"', text))


# ---------------------------------------------------------------------------
# Format a new catalog entry
# ---------------------------------------------------------------------------

OUTCOME_LABELS = {
    "BLOCKED": "blocked / unsupported intent",
    "MISMATCH": f"wrong intent matched",
    "PARTIAL": "supported but response too thin (< {THIN_RESPONSE_CHARS} chars)",
}

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


def format_entry(q: dict, resp: dict, bucket: str) -> str:
    label = q["notes"][:60]
    raw = q["text"]
    category = q["category"]
    priority = PRIORITY_MAP.get(category, "P2")
    date = datetime.date.today().isoformat()
    intent_got = resp.get("intent", "n/a")
    intent_expected = q.get("expected_intent") or "unknown"
    outcome = resp.get("outcome", "n/a")
    final_text = resp.get("final_text", "")[:300]
    app_response_desc = OUTCOME_LABELS.get(bucket, bucket)
    if bucket == "MISMATCH":
        app_response_desc = f"wrong intent matched — got `{intent_got}`, expected `{intent_expected}`"

    return (
        f"\n### {label}\n"
        f"- **Raw prompt:** \"{raw}\"\n"
        f"- **App response:** {app_response_desc}\n"
        f"- **App final_text:** \"{final_text}\"\n"
        f"- **User need:** {q['notes']}\n"
        f"- **Priority:** {priority}\n"
        f"- **Source:** catalog_runner automated scan, {date}\n"
        f"- **Notes:** intent=`{intent_got}` outcome=`{outcome}`\n"
    )


# ---------------------------------------------------------------------------
# Append findings to catalog
# ---------------------------------------------------------------------------

SECTION_HEADERS = {
    "Captain / Vice-Captain": "## Category: Captain / Vice-Captain",
    "Transfer Planning": "## Category: Transfer Planning",
    "Player Pick / Start Recommendation": "## Category: Player Pick / Start Recommendation",
    "Fixture Difficulty / Schedule Analysis": "## Category: Fixture Difficulty / Schedule Analysis",
    "Player Info / Stats": "## Category: Player Info / Stats",
    "Chip Strategy": "## Category: Chip Strategy",
    "Squad / Bench Management": "## Category: Squad / Bench Management",
    "Gameweek Info": "## Category: Gameweek Info",
    "Meta / App Behavior": "## Category: Meta / App Behavior",
    "Other / Uncategorized": "## Category: Other / Uncategorized",
}


def append_to_catalog(catalog: Path, entries_by_category: dict[str, list[str]]) -> int:
    text = catalog.read_text(encoding="utf-8") if catalog.exists() else ""
    total = 0

    for category, entries in entries_by_category.items():
        if not entries:
            continue
        header = SECTION_HEADERS.get(category, f"## Category: {category}")
        if header in text:
            # Inject after the section header line
            text = text.replace(header, header + "".join(entries), 1)
        else:
            # Append new section before the Other/Uncategorized section or at end
            fallback_header = "## Category: Other / Uncategorized"
            block = f"\n---\n\n{header}\n{''.join(entries)}"
            if fallback_header in text:
                text = text.replace(fallback_header, block + "\n\n" + fallback_header, 1)
            else:
                text += "\n" + block
        total += len(entries)

    catalog.write_text(text, encoding="utf-8")
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()
    questions = load_questions()
    known = existing_prompts(CATALOG_PATH)

    print(f"Base URL : {args.base_url}")
    print(f"Questions: {len(questions)}")
    print(f"Catalog  : {CATALOG_PATH}")
    print(f"Dry run  : {args.dry_run}")
    print()

    # Check readiness
    try:
        r = httpx.get(f"{args.base_url.rstrip('/')}/ready", timeout=5)
        if r.status_code != 200:
            print(f"[WARN] /ready returned {r.status_code} — bootstrap may not be loaded")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Could not reach {args.base_url}: {e}")
        print("       Pass --base-url pointing to your Railway deployment.\n")

    results: dict[str, list[str]] = {cat: [] for cat in SECTION_HEADERS}
    counts = {"PASS": 0, "BLOCKED": 0, "MISMATCH": 0, "PARTIAL": 0, "SKIPPED": 0}

    for q in questions:
        prompt = q["text"]
        if prompt in known:
            counts["SKIPPED"] += 1
            print(f"  SKIP  {prompt[:70]}")
            continue

        resp = ask(args.base_url, prompt, args.timeout)
        bucket = classify(q, resp)
        counts[bucket] += 1

        marker = {"PASS": "  OK  ", "BLOCKED": " FAIL ", "MISMATCH": " MISS ", "PARTIAL": " THIN "}[bucket]
        print(f"{marker} [{q['category'][:28]:<28}] {prompt[:60]}")

        if bucket != "PASS":
            entry = format_entry(q, resp, bucket)
            cat = q.get("category", "Other / Uncategorized")
            if cat not in results:
                results["Other / Uncategorized"].append(entry)
            else:
                results[cat].append(entry)

    print()
    print("Results:")
    for k, v in counts.items():
        print(f"  {k:<8}: {v}")

    non_pass = sum(len(v) for v in results.values())
    if non_pass == 0:
        print("\nNo new findings to catalog.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Entries that would be written:\n")
        for cat, entries in results.items():
            for e in entries:
                print(e)
    else:
        written = append_to_catalog(CATALOG_PATH, results)
        print(f"\nWrote {written} new entries to {CATALOG_PATH}")


if __name__ == "__main__":
    main()
