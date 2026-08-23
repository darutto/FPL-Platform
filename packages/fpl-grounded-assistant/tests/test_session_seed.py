"""
tests/test_session_seed.py
===========================
Tests for the optional POST /session seed payload (CreateSessionRequest),
which lets a newly-created follow-up session start with the prior turn's
already-resolved state (last_comparison, last_transfer, etc.) instead of
empty — the fix for follow-up resolvers having no context on the very
first follow-up after a stateless /ask turn.

Covers:
    (i)    No-body / empty-object / explicit-null bodies all behave
           identically to today's contract: 200, empty-state session.
    (ii)   Each of the 5 seed fields individually seeds the expected
           ConversationState field; other fields remain default.
    (iii)  Validation: malformed tuple length, blank/oversized names,
           unknown fields, non-bool last_differential, and setting both
           last_comparison + last_transfer together all reject with 422.
    (iv)   End-to-end: a session seeded with last_comparison correctly
           reaches resolve_comparison_followup_llm on a Spanish/elliptical
           follow-up and rewrites the question (LLM call mocked).
    (v)    A session remains valid/reusable across multiple sessionAsk
           calls regardless of individual-turn outcome.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import fpl_server
from fpl_grounded_assistant import STANDARD_BOOTSTRAP
from fpl_grounded_assistant.reference_resolver import ReferenceResolution


@pytest.fixture(autouse=True)
def _isolated_sessions():
    """Each test gets a clean session registry — avoids cross-test pollution
    and keeps well clear of the 100-session cap."""
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    yield
    fpl_server._sessions.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(fpl_server.app)


def _state_for(client: TestClient, session_id: str):
    return fpl_server._sessions[session_id].session.state


# ---------------------------------------------------------------------------
# (i) No-body / {} / explicit null — all identical to today's contract
# ---------------------------------------------------------------------------

class TestBodilessAndEmptyEquivalence:
    def test_no_body_creates_empty_state_session(self, client: TestClient):
        resp = client.post("/session")
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_comparison is None
        assert state.last_transfer is None
        assert state.last_fixture_run_player is None
        assert state.last_differential is False
        assert state.last_player_query is None

    def test_empty_object_body_creates_empty_state_session(self, client: TestClient):
        resp = client.post("/session", json={})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_comparison is None

    def test_explicit_json_null_body_creates_empty_state_session(self, client: TestClient):
        """A literal JSON `null` body binds identically to no body at all —
        FastAPI resolves the Optional[CreateSessionRequest] param to None in
        both cases. This must be 200 + empty state, NOT a 422 — easy to get
        backwards, asserted explicitly."""
        resp = client.post(
            "/session", content=b"null", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_comparison is None


# ---------------------------------------------------------------------------
# (ii) Each of the 5 fields individually seeds correctly
# ---------------------------------------------------------------------------

class TestIndividualFieldSeeding:
    def test_seeds_last_comparison(self, client: TestClient):
        resp = client.post("/session", json={"last_comparison": ["Haaland", "Salah"]})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_comparison == ("Haaland", "Salah")
        assert state.last_transfer is None
        assert state.last_differential is False

    def test_seeds_last_transfer(self, client: TestClient):
        resp = client.post("/session", json={"last_transfer": ["Rice", "Palmer"]})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_transfer == ("Rice", "Palmer")
        assert state.last_comparison is None

    def test_seeds_last_fixture_run_player(self, client: TestClient):
        resp = client.post("/session", json={"last_fixture_run_player": "Mbappe"})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_fixture_run_player == "Mbappe"

    def test_seeds_last_differential(self, client: TestClient):
        resp = client.post("/session", json={"last_differential": True})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_differential is True

    def test_seeds_last_player_query(self, client: TestClient):
        resp = client.post("/session", json={"last_player_query": "Haaland"})
        assert resp.status_code == 200
        state = _state_for(client, resp.json()["session_id"])
        assert state.last_player_query == "Haaland"


# ---------------------------------------------------------------------------
# (iii) Validation — trust-boundary hardening
# ---------------------------------------------------------------------------

class TestValidationRejections:
    def test_wrong_tuple_length_rejected(self, client: TestClient):
        resp = client.post("/session", json={"last_comparison": ["Haaland"]})
        assert resp.status_code == 422

    def test_blank_name_rejected(self, client: TestClient):
        resp = client.post("/session", json={"last_comparison": ["Haaland", "   "]})
        assert resp.status_code == 422

    def test_oversized_name_rejected(self, client: TestClient):
        resp = client.post(
            "/session", json={"last_fixture_run_player": "x" * 101}
        )
        assert resp.status_code == 422

    def test_unknown_field_rejected(self, client: TestClient):
        resp = client.post("/session", json={"not_a_real_field": "Haaland"})
        assert resp.status_code == 422

    def test_non_bool_last_differential_rejected(self, client: TestClient):
        """StrictBool must reject string/int coercion (e.g. "true", 1) —
        confirms the trust boundary doesn't silently coerce."""
        resp = client.post("/session", json={"last_differential": "true"})
        assert resp.status_code == 422

    def test_both_anchors_set_rejected(self, client: TestClient):
        resp = client.post(
            "/session",
            json={
                "last_comparison": ["Haaland", "Salah"],
                "last_transfer": ["Rice", "Palmer"],
            },
        )
        assert resp.status_code == 422

    def test_malformed_json_rejected(self, client: TestClient):
        resp = client.post(
            "/session", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# (iv) End-to-end: seeded session reaches the comparison-followup resolver
# ---------------------------------------------------------------------------

class TestSeededSessionReachesComparisonFollowup:
    def test_seeded_last_comparison_enables_llm_followup_rewrite(self, client: TestClient):
        create_resp = client.post(
            "/session", json={"last_comparison": ["Haaland", "Salah"]}
        )
        assert create_resp.status_code == 200
        session_id = create_resp.json()["session_id"]

        fake_resolution = ReferenceResolution(
            resolved_query="Semenyo",
            intent_guess=None,
            reference_source="comparison_followup_llm",
            confidence=0.9,
            language="es",
            rewritten_question="compare Haaland and Semenyo",
        )
        def _fake_ask_v2(question, bootstrap, *args, **kwargs):
            # G2 (session/ask parity fix): sessions now route through
            # ask_v2() unconditionally, exactly like POST /ask. ask_v2()'s
            # plain-text path has no deterministic full-intent ladder for
            # multi-player sentences (only for bare player names) --
            # compare_players is resolved by the orchestrator, so it must be
            # mocked here. The assertion is the real proof this test cares
            # about: the REWRITTEN (canonical) question, not the raw
            # "y con Semenyo?", is what reached routing.
            assert question == "compare Haaland and Semenyo"
            return {
                "selected_tool": "compare_players",
                "tool_input": {"query_a": "Haaland", "query_b": "Semenyo"},
                "raw_output": {"status": "ok"},
                "answer_text": "Haaland edges Semenyo.",
                "outcome": "ok",
                "kind": "text",
                "routing_trace": {
                    "branch": "orchestrator",
                    "orchestrator_called": True,
                    "orchestrator_outcome": "ok",
                    "grounded": True,
                },
                "tokens": {"total": 123},
            }

        with patch(
            "fpl_grounded_assistant.reference_resolver.resolve_comparison_followup_llm",
            return_value=fake_resolution,
        ) as mock_resolver, patch(
            "fpl_grounded_assistant.harness.ask_v2",
            side_effect=_fake_ask_v2,
        ):
            ask_resp = client.post(
                f"/session/{session_id}/ask", json={"question": "y con Semenyo?"}
            )

        assert ask_resp.status_code == 200
        mock_resolver.assert_called_once()
        body = ask_resp.json()
        assert body["intent"] == "compare_players"


# ---------------------------------------------------------------------------
# (v) Session remains reusable across multiple turns
# ---------------------------------------------------------------------------

class TestSessionReusability:
    def test_session_remains_usable_after_a_turn_regardless_of_outcome(
        self, client: TestClient
    ):
        create_resp = client.post("/session")
        session_id = create_resp.json()["session_id"]

        first = client.post(
            f"/session/{session_id}/ask",
            json={"question": "asdkjaslkdj nonsense question"},
        )
        assert first.status_code == 200  # never a hard failure, just outcome != ok

        second = client.post(
            f"/session/{session_id}/ask", json={"question": "who should I captain"}
        )
        assert second.status_code == 200
        assert session_id in fpl_server._sessions
