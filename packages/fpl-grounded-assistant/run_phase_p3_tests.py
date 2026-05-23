"""
run_phase_p3_tests.py
=====================
Phase P3.1: Quota meter + audit log tests.

Sections
--------
Q  Quota basic behavior (Q1-Q10)
A  Audit write and estimate (A1-A8)
H  HTTP integration (H1-H4)

~30 assertions.  Exit code 0 on success, 1 on any failure.

Run from packages/fpl-grounded-assistant::

    python run_phase_p3_tests.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Path setup (mirrors all other run_phase_*.py files)
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

from fpl_grounded_assistant.quota import (
    QuotaTier,
    QuotaCheck,
    TIERS,
    check_quota,
    record_turn,
    get_quota_status,
    reset_quota,
)
from fpl_grounded_assistant.audit import (
    AuditEntry,
    write_audit_entry,
    estimate_usd_cost,
    make_audit_entry,
    PROVIDER_PRICING_PER_1M,
)
from fpl_grounded_assistant.dispatcher import OUTCOME_QUOTA_EXCEEDED
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

_pass = 0
_fail = 0


def ok(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {label}")
    else:
        _fail += 1
        print(f"  FAIL  {label}")


# ---------------------------------------------------------------------------
# Q: Quota basic behavior
# ---------------------------------------------------------------------------

print("\n=== Q: Quota basic behavior ===")

# Always start from a clean slate.
reset_quota()

# Q1: Fresh user is allowed.
_q1 = check_quota("user_q1", "free")
ok(_q1.allowed, "Q1: fresh user is allowed")

# Q2: Over daily message cap -> blocked.
reset_quota()
_free_tier = TIERS["free"]
for _ in range(_free_tier.daily_message_cap):
    record_turn("user_q2", 0, "free")  # consume all daily messages
_q2 = check_quota("user_q2", "free")
ok(not _q2.allowed, "Q2: over daily message cap -> not allowed")
ok(_q2.reason == "daily_message_cap_exceeded", "Q2b: reason is daily_message_cap_exceeded")

# Q3: Over daily token cap -> blocked.
reset_quota()
# Inject enough tokens to exceed daily cap in one turn (we manipulate store directly).
from fpl_grounded_assistant.quota import _store, _UserBucket
import time as _time
_now = _time.time()
_store["user_q3"] = _UserBucket(
    daily=[(_now, _free_tier.daily_token_cap, 1)],
    monthly=[(_now, _free_tier.daily_token_cap, 1)],
)
_q3 = check_quota("user_q3", "free")
ok(not _q3.allowed, "Q3: over daily token cap -> not allowed")
ok(_q3.reason == "daily_token_cap_exceeded", "Q3b: reason is daily_token_cap_exceeded")

# Q4: reset_quota clears a specific user.
reset_quota("user_q3")
_q4 = check_quota("user_q3", "free")
ok(_q4.allowed, "Q4: after reset_quota(user) -> allowed again")

# Q4b: reset_quota(None) clears all users.
record_turn("user_q4a", 100, "free")
record_turn("user_q4b", 100, "free")
reset_quota()
_q4b = check_quota("user_q4a", "free")
ok(_q4b.allowed and _q4b.daily_tokens_used == 0, "Q4b: reset_quota() clears all users")

# Q5: Tier-specific caps respected (patreon_basic >> free).
reset_quota()
_basic = TIERS["patreon_basic"]
ok(_basic.daily_message_cap > _free_tier.daily_message_cap,
   "Q5: patreon_basic daily_message_cap > free daily_message_cap")
ok(_basic.daily_token_cap > _free_tier.daily_token_cap,
   "Q5b: patreon_basic daily_token_cap > free daily_token_cap")

# Q6: record_turn increments daily + monthly counters.
reset_quota()
record_turn("user_q6", 500, "free")
_q6 = check_quota("user_q6", "free")
ok(_q6.daily_tokens_used == 500, "Q6: daily tokens correctly incremented")
ok(_q6.monthly_tokens_used == 500, "Q6b: monthly tokens correctly incremented")
ok(_q6.daily_message_count == 1, "Q6c: daily message count == 1 after one turn")

# Q7: record_turn is additive across multiple turns.
reset_quota()
record_turn("user_q7", 300, "free")
record_turn("user_q7", 200, "free")
_q7 = check_quota("user_q7", "free")
ok(_q7.daily_tokens_used == 500, "Q7: token counts accumulate across turns")
ok(_q7.daily_message_count == 2, "Q7b: message count accumulates across turns")

# Q8: Over monthly message cap -> blocked (inject entries directly).
reset_quota()
from fpl_grounded_assistant.quota import _MONTHLY_WINDOW_S
_monthly_now = _time.time()
_store["user_q8"] = _UserBucket(
    daily=[],  # daily empty (only monthly exhausted)
    monthly=[(_monthly_now - 1, 0, _free_tier.monthly_message_cap)],
)
_q8 = check_quota("user_q8", "free")
ok(not _q8.allowed and _q8.reason == "monthly_message_cap_exceeded",
   "Q8: monthly_message_cap exhausted -> blocked")

# Q9: QuotaCheck has upgrade prompts populated when blocked.
ok(_q8.upgrade_prompt_es is not None, "Q9: upgrade_prompt_es populated when blocked")
ok(_q8.upgrade_prompt_en is not None, "Q9b: upgrade_prompt_en populated when blocked")

# Q10: get_quota_status is read-only (does not mutate).
reset_quota()
record_turn("user_q10", 100, "free")
_before = get_quota_status("user_q10", "free")
_after  = get_quota_status("user_q10", "free")
ok(_before.daily_tokens_used == _after.daily_tokens_used,
   "Q10: get_quota_status is idempotent (read-only)")


# ---------------------------------------------------------------------------
# A: Audit write and USD cost estimation
# ---------------------------------------------------------------------------

print("\n=== A: Audit write and estimate ===")

# Use a temp directory so we don't pollute the real audit_logs/.
_tmpdir = tempfile.mkdtemp()


def _make_entry(**kwargs) -> AuditEntry:
    """Build a minimal AuditEntry for testing."""
    defaults = dict(
        user_id="test_user",
        tier="free",
        question="who should I captain?",
        branch="orchestrator",
        outcome="ok",
        intent="captain_score",
        tokens={"primary_input": 1000, "primary_output": 200, "total": 1200},
        provider="gemini",
        final_text="Haaland is your best captain option.",
    )
    defaults.update(kwargs)
    return make_audit_entry(**defaults)


# A1: write_audit_entry creates the file and appends.
_e1 = _make_entry()
write_audit_entry(_e1, log_dir=_tmpdir)
_files_a1 = [f for f in os.listdir(_tmpdir) if f.endswith(".ndjson")]
ok(len(_files_a1) == 1, "A1: one NDJSON file created after first write")

# A2: Multi-entry append.
_e2 = _make_entry(question="should I use triple captain?")
write_audit_entry(_e2, log_dir=_tmpdir)
_log_path = os.path.join(_tmpdir, _files_a1[0])
with open(_log_path, encoding="utf-8") as _f:
    _lines = [l.strip() for l in _f if l.strip()]
ok(len(_lines) == 2, "A2: two lines after two writes (append, not overwrite)")

# A3: Directory auto-created when absent.
import shutil
_tmpdir2 = os.path.join(_tmpdir, "nested", "audit")
_e3 = _make_entry()
write_audit_entry(_e3, log_dir=_tmpdir2)
ok(os.path.isdir(_tmpdir2), "A3: nested log directory auto-created")
shutil.rmtree(_tmpdir2, ignore_errors=True)

# A4: Each line is independently JSON-decodable.
_all_valid = True
with open(_log_path, encoding="utf-8") as _f:
    for _line in _f:
        _line = _line.strip()
        if not _line:
            continue
        try:
            _obj = json.loads(_line)
        except json.JSONDecodeError:
            _all_valid = False
ok(_all_valid, "A4: every line in NDJSON file is valid JSON")

# A5: usd_cost_estimate non-zero for non-trivial token usage.
_cost_a5 = estimate_usd_cost({"primary_input": 1000, "primary_output": 200}, "gemini")
ok(_cost_a5 > 0.0, "A5: usd_cost_estimate > 0 for non-zero token usage")

# A6: Gemini is cheaper than Anthropic for same tokens.
_tokens_test = {"primary_input": 1000, "primary_output": 500}
_cost_gemini    = estimate_usd_cost(_tokens_test, "gemini")
_cost_anthropic = estimate_usd_cost(_tokens_test, "anthropic")
ok(_cost_gemini < _cost_anthropic, "A6: Gemini cost < Anthropic cost for same tokens")

# A7: Per-1M math is correct for Gemini input (0.075 per 1M = 0.000000075 per token).
_cost_a7 = estimate_usd_cost({"primary_input": 1_000_000}, "gemini")
_expected = PROVIDER_PRICING_PER_1M["gemini"]["input"]
ok(abs(_cost_a7 - _expected) < 1e-6, f"A7: 1M input tokens cost = {_expected} (got {_cost_a7:.8f})")

# A8: Cache-read tokens cheaper than input tokens (same provider).
_cost_input = estimate_usd_cost({"primary_input": 1_000_000}, "anthropic")
_cost_cache = estimate_usd_cost({"primary_cache_read": 1_000_000}, "anthropic")
ok(_cost_cache < _cost_input, "A8: cache_read tokens cheaper than input tokens (Anthropic)")

# Cleanup temp dir.
shutil.rmtree(_tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# H: HTTP integration
# ---------------------------------------------------------------------------

print("\n=== H: HTTP integration ===")

import fpl_server
from fastapi.testclient import TestClient

# Reset quota + bootstrap state before HTTP tests.
reset_quota()
fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
fpl_server._init_classifier_client(None)


def _make_http_client() -> TestClient:
    return TestClient(fpl_server.app, raise_server_exceptions=True)


# H1: POST /ask with X-User-Id header records turn + writes audit entry.
# We verify indirectly: after one ask, quota status shows a consumed message.
reset_quota()
_client_h1 = _make_http_client()
_resp_h1 = _client_h1.post(
    "/ask",
    json={"question": "what is the current gameweek"},
    headers={"X-User-Id": "http_user_h1"},
)
ok(_resp_h1.status_code == 200, "H1: POST /ask returns 200")
_qs_h1 = get_quota_status("http_user_h1", "free")
ok(_qs_h1.daily_message_count == 1, "H1b: record_turn fired — daily_message_count == 1")

# H2: Quota-exceeded returns 200 with outcome="quota_exceeded" (soft-fail, not 4xx).
reset_quota()
# Exhaust the daily message cap for a specific user.
_test_uid_h2 = "http_user_h2"
for _ in range(_free_tier.daily_message_cap):
    record_turn(_test_uid_h2, 0, "free")

_client_h2 = _make_http_client()
_resp_h2 = _client_h2.post(
    "/ask",
    json={"question": "who should I captain"},
    headers={"X-User-Id": _test_uid_h2},
)
ok(_resp_h2.status_code == 200, "H2: quota-exceeded returns HTTP 200 (soft-fail)")
_body_h2 = _resp_h2.json()
ok(_body_h2.get("outcome") == OUTCOME_QUOTA_EXCEEDED,
   f"H2b: outcome == 'quota_exceeded' (got {_body_h2.get('outcome')})")
ok(_body_h2.get("supported") is False, "H2c: supported=False on quota exceeded")

# H3: GET /quota returns current status JSON.
reset_quota()
record_turn("http_user_h3", 1000, "free")
_client_h3 = _make_http_client()
_resp_h3 = _client_h3.get("/quota", params={"user_id": "http_user_h3", "tier": "free"})
ok(_resp_h3.status_code == 200, "H3: GET /quota returns 200")
_body_h3 = _resp_h3.json()
ok(_body_h3.get("daily_tokens_used") == 1000,
   f"H3b: GET /quota returns correct token count (got {_body_h3.get('daily_tokens_used')})")
ok("daily_message_cap" in _body_h3, "H3c: GET /quota response includes daily_message_cap")

# H4: Session ask honors quota same as /ask.
reset_quota()
_test_uid_h4 = "http_user_h4"
for _ in range(_free_tier.daily_message_cap):
    record_turn(_test_uid_h4, 0, "free")

_client_h4 = _make_http_client()
# Create a session first.
_sess_resp = _client_h4.post("/session")
ok(_sess_resp.status_code == 200, "H4: POST /session creates session")
_sess_id = _sess_resp.json()["session_id"]

# Now try to ask within the session — should be blocked by quota.
_resp_h4 = _client_h4.post(
    f"/session/{_sess_id}/ask",
    json={"question": "who should I captain"},
    headers={"X-User-Id": _test_uid_h4},
)
ok(_resp_h4.status_code == 200, "H4b: session ask quota-exceeded returns HTTP 200")
_body_h4 = _resp_h4.json()
ok(_body_h4.get("outcome") == OUTCOME_QUOTA_EXCEEDED,
   f"H4c: session ask outcome == 'quota_exceeded' (got {_body_h4.get('outcome')})")


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

print()
print("=" * 50)
print(f"Phase P3 results: {_pass}/{_pass + _fail} PASS")
if _fail:
    print(f"  {_fail} FAILED.")
else:
    print("  All assertions PASSED.")
print("=" * 50)
sys.exit(0 if _fail == 0 else 1)
