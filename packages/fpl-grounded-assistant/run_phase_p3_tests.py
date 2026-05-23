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
    hash_user_id,
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
# P3.f (F5): the server hashes X-User-Id before keying quota, so we must look
# up the hashed id.
reset_quota()
_client_h1 = _make_http_client()
_resp_h1 = _client_h1.post(
    "/ask",
    json={"question": "what is the current gameweek"},
    headers={"X-User-Id": "http_user_h1"},
)
ok(_resp_h1.status_code == 200, "H1: POST /ask returns 200")
_qs_h1 = get_quota_status(hash_user_id("http_user_h1"), "free")
ok(_qs_h1.daily_message_count == 1, "H1b: record_turn fired — daily_message_count == 1")

# H2: Quota-exceeded returns 200 with outcome="quota_exceeded" (soft-fail, not 4xx).
# P3.f (F5): the server hashes X-User-Id, so we exhaust the cap under the HASHED id.
reset_quota()
_test_uid_h2 = "http_user_h2"
_test_uid_h2_hashed = hash_user_id(_test_uid_h2)
for _ in range(_free_tier.daily_message_cap):
    record_turn(_test_uid_h2_hashed, 0, "free")

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
# P3.f (F5): exhaust cap under the HASHED id (server hashes X-User-Id at intake).
reset_quota()
_test_uid_h4 = "http_user_h4"
_test_uid_h4_hashed = hash_user_id(_test_uid_h4)
for _ in range(_free_tier.daily_message_cap):
    record_turn(_test_uid_h4_hashed, 0, "free")

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
# R: P3.f Adversarial Remediation assertions (F1, F2, F5, F8)
# ---------------------------------------------------------------------------

print("\n=== R: P3.f Adversarial Remediation (F1/F2/F5/F8) ===")

import logging as _logging
import unittest.mock as _mock

# R1: hash_user_id("alice") returns a 16-hex-char string, NOT "alice".
_r1_hash = hash_user_id("alice")
ok(len(_r1_hash) == 16, "R1: hash_user_id returns 16-char string")
ok(_r1_hash != "alice", "R1b: hash_user_id does not return raw value")
ok(all(c in "0123456789abcdef" for c in _r1_hash), "R1c: hash_user_id returns hex string")

# R2: hash_user_id("anonymous") returns "anonymous" unchanged.
ok(hash_user_id("anonymous") == "anonymous", "R2: hash_user_id('anonymous') preserved")

# R3: hash_user_id("") returns "anonymous".
ok(hash_user_id("") == "anonymous", "R3: hash_user_id('') returns 'anonymous'")

# R4: Same input -> same hash (deterministic).
ok(hash_user_id("alice") == hash_user_id("alice"), "R4: hash_user_id is deterministic")

# R5: Different inputs -> different hashes.
ok(hash_user_id("alice") != hash_user_id("bob"), "R5: different inputs produce different hashes")

# R6: POST /ask with X-User-Id: alice -> audit log user_id is the hash, not "alice".
reset_quota()
_r6_tmpdir = tempfile.mkdtemp()
_r6_orig_log_dir = None

# Patch write_audit_entry to capture the entry passed to it.
_r6_captured: list = []
import fpl_grounded_assistant.audit as _audit_mod

_r6_orig_write = _audit_mod.write_audit_entry

def _r6_capture(entry, log_dir=None):
    _r6_captured.append(entry)
    _r6_orig_write(entry, log_dir=_r6_tmpdir)

with _mock.patch.object(_audit_mod, "write_audit_entry", side_effect=_r6_capture):
    # Also patch in fpl_server namespace since it imported the function.
    import fpl_server as _fpl_server
    with _mock.patch.object(_fpl_server, "write_audit_entry", side_effect=_r6_capture):
        _r6_client = _make_http_client()
        _r6_resp = _r6_client.post(
            "/ask",
            json={"question": "what is the current gameweek"},
            headers={"X-User-Id": "alice"},
        )

_r6_alice_hash = hash_user_id("alice")
_r6_audit_user_ids = [e.user_id for e in _r6_captured]
ok(
    any(uid == _r6_alice_hash for uid in _r6_audit_user_ids),
    f"R6: audit entry user_id is hash ({_r6_alice_hash}), not 'alice' (got {_r6_audit_user_ids})",
)
ok(
    not any(uid == "alice" for uid in _r6_audit_user_ids),
    "R6b: raw 'alice' never appears in audit user_id field",
)
import shutil as _shutil
_shutil.rmtree(_r6_tmpdir, ignore_errors=True)

# R7: @resource query -> no quota_exceeded even when daily cap hit; tokens=0 in quota.
reset_quota()
_r7_uid_raw = "r7_user"
_r7_uid_hashed = hash_user_id(_r7_uid_raw)
# Exhaust cap.
for _ in range(_free_tier.daily_message_cap):
    record_turn(_r7_uid_hashed, 0, "free")
_r7_client = _make_http_client()
_r7_resp = _r7_client.post(
    "/ask",
    json={"question": "@captain Haaland"},
    headers={"X-User-Id": _r7_uid_raw},
)
ok(_r7_resp.status_code == 200, "R7: @resource query returns 200 even at cap")
_r7_body = _r7_resp.json()
ok(
    _r7_body.get("outcome") != OUTCOME_QUOTA_EXCEEDED,
    f"R7b: @resource outcome != quota_exceeded (got {_r7_body.get('outcome')})",
)

# R8: /prompt query -> same exemption as @resource.
reset_quota()
_r8_uid_raw = "r8_user"
_r8_uid_hashed = hash_user_id(_r8_uid_raw)
for _ in range(_free_tier.daily_message_cap):
    record_turn(_r8_uid_hashed, 0, "free")
_r8_client = _make_http_client()
_r8_resp = _r8_client.post(
    "/ask",
    json={"question": "/captain"},
    headers={"X-User-Id": _r8_uid_raw},
)
ok(_r8_resp.status_code == 200, "R8: /prompt query returns 200 even at cap")
_r8_body = _r8_resp.json()
ok(
    _r8_body.get("outcome") != OUTCOME_QUOTA_EXCEEDED,
    f"R8b: /prompt outcome != quota_exceeded (got {_r8_body.get('outcome')})",
)

# R9: FPL_SESSION_ENABLED=false -> POST /session returns 503 (operator kill-switch).
import os as _os
_r9_orig = _os.environ.get("FPL_SESSION_ENABLED")
_os.environ["FPL_SESSION_ENABLED"] = "false"
_r9_client = _make_http_client()
_r9_resp = _r9_client.post("/session")
ok(_r9_resp.status_code == 503, "R9: FPL_SESSION_ENABLED=false -> POST /session returns 503")
# Also check /session/{id}/ask is blocked.
_r9_ask_resp = _r9_client.post("/session/fake-id/ask", json={"question": "who should I captain"})
ok(_r9_ask_resp.status_code == 503, "R9b: FPL_SESSION_ENABLED=false -> session ask returns 503")
# Restore.
if _r9_orig is None:
    _os.environ.pop("FPL_SESSION_ENABLED", None)
else:
    _os.environ["FPL_SESSION_ENABLED"] = _r9_orig

# R10-R12: audit write failure -> logger.exception fires (observable signal, no crash).
reset_quota()
_r10_log_records: list = []

class _CapturingHandler(_logging.Handler):
    def emit(self, record):
        _r10_log_records.append(record)

_r10_handler = _CapturingHandler()
_r10_logger = _logging.getLogger("fpl_server")
_r10_logger.addHandler(_r10_handler)
_r10_logger.setLevel(_logging.WARNING)

# Make write_audit_entry raise so the except-block fires.
def _r10_failing_write(entry, log_dir=None):
    raise OSError("simulated disk full")

with _mock.patch.object(_fpl_server, "write_audit_entry", side_effect=_r10_failing_write):
    _r10_client = _make_http_client()
    _r10_resp = _r10_client.post(
        "/ask",
        json={"question": "what is the current gameweek"},
        headers={"X-User-Id": "r10_user"},
    )

_r10_logger.removeHandler(_r10_handler)

ok(_r10_resp.status_code == 200, "R10: endpoint returns 200 even when audit write fails")
_r10_exc_records = [r for r in _r10_log_records if r.levelno >= _logging.ERROR]
ok(len(_r10_exc_records) >= 1, f"R11: logger.exception fired on audit write failure (got {len(_r10_exc_records)} error records)")
ok(
    any("audit write failed" in (r.getMessage() if callable(r.getMessage) else str(r.msg)) for r in _r10_exc_records),
    "R12: logger.exception message contains 'audit write failed'",
)


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
