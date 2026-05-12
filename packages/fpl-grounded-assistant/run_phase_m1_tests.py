"""
run_phase_m1_tests.py
======================
Phase M1 (MCP_architecture): Resource Surface tests.

Covers:
    A  input_normalizer
    B  intent_aliases (Spanish + English alias resolution)
    C  resource_registry (all six resources return non-empty rows)
    D  decision_router (resource / prompt / text / unsupported branches)
    E  ask_v2() (resource + unsupported + plain-text regression vs ask())
    F  GET /resources introspection
    G  @injuries recency sort

Run from packages/fpl-grounded-assistant::

    python run_phase_m1_tests.py

Total assertions: ≥30 (per agent spec). Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations

import copy
import os
import sys

# ---------------------------------------------------------------------------
# Path setup (matches run_phase9c_tests.py)
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.dirname(_HERE)
for _pkg in [
    _HERE,
    os.path.join(_PKGS, "fpl-api-client"),
    os.path.join(_PKGS, "fpl-data-core"),
    os.path.join(_PKGS, "fpl-player-registry"),
    os.path.join(_PKGS, "fpl-query-tools"),
    os.path.join(_PKGS, "fpl-tool-contract"),
    os.path.join(_PKGS, "fpl-tool-runner"),
    os.path.join(_PKGS, "fpl-captain-engine"),
    os.path.join(_PKGS, "fpl-pipeline"),
]:
    if _pkg not in sys.path:
        sys.path.insert(0, _pkg)

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from fpl_grounded_assistant import ask, ask_v2  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.intent_aliases import (  # noqa: E402
    RESOURCE_CANONICAL, resolve_resource, list_resources,
)
from fpl_grounded_assistant.input_normalizer import (  # noqa: E402
    normalize, ResourceInput, PromptInput, TextInput, RejectedInput,
)
from fpl_grounded_assistant.resource_registry import (  # noqa: E402
    list_resource_specs, run_resource, has_resource,
)
from fpl_grounded_assistant.decision_router import decide  # noqa: E402

# ---------------------------------------------------------------------------
# Test plumbing
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0
_failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        _failures.append(label)
        print(f"  FAIL  {label}")


# Build a richer bootstrap so total_points and news_added are present
# for the recency-sort and top_points tests.
def _build_test_bootstrap() -> dict:
    bs = copy.deepcopy(STANDARD_BOOTSTRAP)
    # Inject total_points and news_added on every element so all six
    # resources have data to rank/sort.
    # Saka (status=d) — most recent news; De Bruyne (status=i) — older news.
    name_to_news = {
        "Saka":      "2026-05-10T09:00:00Z",
        "De Bruyne": "2026-04-01T12:00:00Z",
    }
    for el in bs["elements"]:
        el.setdefault("total_points", 100)
        el["news_added"] = name_to_news.get(el.get("web_name"), "")
    # Make Haaland the highest-points player.
    for el in bs["elements"]:
        if el.get("web_name") == "Haaland":
            el["total_points"] = 250
        elif el.get("web_name") == "Salah":
            el["total_points"] = 230
    return bs


BOOTSTRAP = _build_test_bootstrap()


# ===========================================================================
# A — input_normalizer
# ===========================================================================
print("\n[A] input_normalizer")

n1 = normalize("@injuries")
check(isinstance(n1, ResourceInput) and n1.canonical == "injuries",
      "A1: '@injuries' -> ResourceInput(canonical=injuries)")

n2 = normalize("  @LESIONADOS  ")
check(isinstance(n2, ResourceInput) and n2.canonical == "injuries",
      "A2: '  @LESIONADOS  ' -> Spanish alias resolves + trim works")

n3 = normalize("/capitan Haaland")
check(isinstance(n3, PromptInput) and n3.name == "capitan" and "Haaland" in n3.args_text,
      "A3: '/capitan Haaland' -> PromptInput")

n4 = normalize("should I captain Haaland")
check(isinstance(n4, TextInput) and "captain" in n4.text.lower(),
      "A4: plain text -> TextInput")

n5 = normalize("   ")
check(isinstance(n5, RejectedInput),
      "A5: blank string -> RejectedInput")

n6 = normalize("oye, @injuries")
check(isinstance(n6, ResourceInput) and n6.canonical == "injuries",
      "A6: Spanish honorific 'oye,' stripped before resource detection")

n7 = normalize("hola @lesionados")
check(isinstance(n7, ResourceInput) and n7.canonical == "injuries",
      "A7: 'hola' honorific stripped, Spanish alias resolves")


# ===========================================================================
# B — intent_aliases
# ===========================================================================
print("\n[B] intent_aliases")

check(len(RESOURCE_CANONICAL) == 6,
      "B1: RESOURCE_CANONICAL has exactly six entries")

expected = {"injuries", "top_form", "top_xg", "top_points", "top_minutes", "popular"}
check(set(list_resources()) == expected,
      "B2: list_resources() returns the six canonical names")

check(resolve_resource("@lesionados") == "injuries",
      "B3: Spanish alias 'lesionados' -> 'injuries'")

check(resolve_resource("FORMA") == "top_form",
      "B4: Spanish alias 'FORMA' (uppercase) -> 'top_form'")

check(resolve_resource("populares") == "popular",
      "B5: Spanish alias 'populares' -> 'popular'")

check(resolve_resource("top_xg") == "top_xg",
      "B6: English canonical 'top_xg' resolves to itself")

check(resolve_resource("unknown_zzz") is None,
      "B7: unknown alias resolves to None")


# ===========================================================================
# C — resource_registry: all six return non-empty rows
# ===========================================================================
print("\n[C] resource_registry")

check(len(list_resource_specs()) == 6,
      "C1: list_resource_specs() returns six specs")

for spec in list_resource_specs():
    res = run_resource(spec.name, BOOTSTRAP)
    check(res.resource == spec.name,
          f"C-{spec.name}-id: result.resource == spec.name")
    check(len(res.rows) > 0,
          f"C-{spec.name}-rows: non-empty rows on test bootstrap")
    # uniform column contract
    check(isinstance(res.columns, tuple) and len(res.columns) >= 3,
          f"C-{spec.name}-cols: columns tuple present")


# ===========================================================================
# D — decision_router
# ===========================================================================
print("\n[D] decision_router")

d1 = decide("@injuries", BOOTSTRAP)
check(d1["kind"] == "resource" and d1["outcome"] == "ok" and d1.get("resource") == "injuries",
      "D1: '@injuries' decides resource/ok/injuries")

d2 = decide("@unknown", BOOTSTRAP)
check(d2["outcome"] == "unsupported" and len(d2.get("suggestions", [])) == 6,
      "D2: '@unknown' -> unsupported with six suggestions")

d3 = decide("should I captain Haaland", BOOTSTRAP)
check(d3["kind"] == "text" and d3["outcome"] == "fallthrough",
      "D3: plain text -> fallthrough")

d4 = decide("/capitan Haaland", BOOTSTRAP)
check(d4["kind"] == "prompt" and d4["outcome"] == "unsupported",
      "D4: '/capitan ...' -> prompt/unsupported in M1 (M2 owns prompts)")


# ===========================================================================
# E — ask_v2 contract
# ===========================================================================
print("\n[E] ask_v2")

v1 = ask_v2("@injuries", BOOTSTRAP)
check(v1.get("outcome") == "ok" and v1.get("kind") == "resource",
      "E1: ask_v2('@injuries') -> outcome=ok, kind=resource")

rr = v1.get("resource_rows") or {}
check(isinstance(rr.get("rows"), list) and len(rr["rows"]) > 0,
      "E2: ask_v2('@injuries').resource_rows.rows non-empty")

check("routing_trace" in v1,
      "E3: ask_v2 returns routing_trace key")

v2 = ask_v2("@unknown", BOOTSTRAP)
check(v2.get("outcome") == "unsupported"
      and isinstance(v2.get("suggestions"), list)
      and set(v2["suggestions"]) == {f"@{n}" for n in list_resources()},
      "E4: ask_v2('@unknown') -> outcome=unsupported, suggestions list six resources")

# Regression guard: text input must match today's ask()
v3 = ask_v2("should I captain Haaland", BOOTSTRAP)
a3 = ask("should I captain Haaland", BOOTSTRAP)
check(v3.get("selected_tool") == a3.get("selected_tool"),
      "E5: ask_v2 plain-text selected_tool matches ask()")
check(v3.get("tool_input") == a3.get("tool_input"),
      "E6: ask_v2 plain-text tool_input matches ask()")
check(v3.get("answer_text") == a3.get("answer_text"),
      "E7: ask_v2 plain-text answer_text matches ask()")


# ===========================================================================
# F — GET /resources introspection
# ===========================================================================
print("\n[F] GET /resources")

try:
    import fpl_server  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    client = TestClient(fpl_server.app)
    r = client.get("/resources")
    check(r.status_code == 200, "F1: GET /resources returns 200")
    body = r.json()
    check(body.get("count") == 6, "F2: /resources count == 6")
    names = [e["name"] for e in body.get("resources", [])]
    check(set(names) == {"injuries", "top_form", "top_xg", "top_points",
                         "top_minutes", "popular"},
          "F3: /resources lists exactly the six canonical names")
except Exception as exc:
    check(False, f"F: /resources endpoint raised: {exc}")


# ===========================================================================
# G — @injuries recency sort
# ===========================================================================
print("\n[G] @injuries recency sort")

g = ask_v2("@injuries", BOOTSTRAP)
rows = (g.get("resource_rows") or {}).get("rows", [])
check(len(rows) >= 2, "G1: at least two unavailable players to sort")
# Saka has news_added 2026-05-10, De Bruyne has 2026-04-01.
# Saka should come BEFORE De Bruyne (newest first).
names = [r.get("web_name") for r in rows]
if "Saka" in names and "De Bruyne" in names:
    check(names.index("Saka") < names.index("De Bruyne"),
          "G2: Saka (newer news_added) appears before De Bruyne (older)")
else:
    check(False, f"G2: expected Saka and De Bruyne in injury list, got {names}")


# ===========================================================================
# Summary
# ===========================================================================
print(f"\n{'='*60}")
print(f"Phase M1 results: {_pass} PASS, {_fail} FAIL  (total {_pass+_fail})")
if _failures:
    print("Failures:")
    for f in _failures:
        print(f"  - {f}")
print(f"{'='*60}")

sys.exit(0 if _fail == 0 else 1)
