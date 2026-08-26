"""
tests/test_squad_tool_team_id_wiring.py
=========================================
i39: team_id carrier wiring — the request-path piece of "expose the user's
squad as a tool the model can consult".

The tool itself (get_my_squad.py) is unit-tested separately
(tests/test_get_my_squad.py). This file pins the *plumbing* contract: how
``ask_v2()``'s ``team_id`` parameter reaches the bootstrap dict that
``run_tool`` / deterministic tool callers actually see, and — the load-bearing
half of the design decision behind i39 — that it does so WITHOUT mutating the
shared bootstrap dict in place.

Test suites
-----------
A.  ask_v2(team_id=...) — injects bootstrap["_my_team_id"] onto a copy
B.  ask_v2(team_id=None) — the original bootstrap object is untouched,
    identically, byte-for-byte, to before this feature existed
C.  AskRequest — accepts an optional team_id field, defaults to None
D.  fpl_server POST /ask — threads req.team_id into ask_v2()
"""
from __future__ import annotations

from typing import Any

import pytest


# ===========================================================================
# A. ask_v2(team_id=...) injects bootstrap["_my_team_id"] onto a copy
# ===========================================================================

class TestTeamIdInjectedOntoCopy:
    def test_route_branch_bootstrap_carries_team_id(self, bootstrap, monkeypatch):
        # "Who is Salah?" resolves deterministically via the router (branch
        # "route"), which calls player_lookup.execute_player_lookup ->
        # get_player_snapshot(..., bootstrap=actual_bootstrap) — the same
        # actual_bootstrap ask_v2() builds team_id injection on top of.
        from fpl_grounded_assistant import harness, player_lookup

        seen: dict[str, Any] = {}
        real_get_player_snapshot = player_lookup.get_player_snapshot

        def _spy(query, bootstrap):
            seen["bootstrap"] = bootstrap
            return real_get_player_snapshot(query, bootstrap=bootstrap)

        monkeypatch.setattr(player_lookup, "get_player_snapshot", _spy)
        result = harness.ask_v2("Who is Salah?", bootstrap, team_id=99999)

        assert result["routing_trace"]["branch"] == "route"
        assert seen["bootstrap"]["_my_team_id"] == 99999

    def test_original_bootstrap_dict_is_not_mutated(self, bootstrap):
        from fpl_grounded_assistant import harness

        assert "_my_team_id" not in bootstrap
        harness.ask_v2("Who is Salah?", bootstrap, team_id=99999)
        # The caller's dict must come back exactly as it went in — the whole
        # point of copying instead of mutating the shared server bootstrap.
        assert "_my_team_id" not in bootstrap

    def test_a_copy_is_made_not_the_same_object(self, bootstrap, monkeypatch):
        from fpl_grounded_assistant import harness, player_lookup

        seen: dict[str, Any] = {}
        real_get_player_snapshot = player_lookup.get_player_snapshot

        def _spy(query, bootstrap):
            seen["bootstrap"] = bootstrap
            return real_get_player_snapshot(query, bootstrap=bootstrap)

        monkeypatch.setattr(player_lookup, "get_player_snapshot", _spy)
        harness.ask_v2("Who is Salah?", bootstrap, team_id=99999)

        assert seen["bootstrap"] is not bootstrap


# ===========================================================================
# B. ask_v2(team_id=None) — identical to pre-i39 behaviour
# ===========================================================================

class TestNoTeamIdIsANoOp:
    def test_default_omits_the_key_entirely(self, bootstrap, monkeypatch):
        from fpl_grounded_assistant import harness, player_lookup

        seen: dict[str, Any] = {}
        real_get_player_snapshot = player_lookup.get_player_snapshot

        def _spy(query, bootstrap):
            seen["bootstrap"] = bootstrap
            return real_get_player_snapshot(query, bootstrap=bootstrap)

        monkeypatch.setattr(player_lookup, "get_player_snapshot", _spy)
        harness.ask_v2("Who is Salah?", bootstrap)  # team_id omitted

        assert "_my_team_id" not in seen["bootstrap"]

    def test_no_team_id_reuses_the_same_bootstrap_object(self, bootstrap, monkeypatch):
        # No team_id -> no copy at all. This is the actual no-cost guarantee
        # the board card asked for: an anonymous turn pays nothing extra.
        from fpl_grounded_assistant import harness, player_lookup

        seen: dict[str, Any] = {}
        real_get_player_snapshot = player_lookup.get_player_snapshot

        def _spy(query, bootstrap):
            seen["bootstrap"] = bootstrap
            return real_get_player_snapshot(query, bootstrap=bootstrap)

        monkeypatch.setattr(player_lookup, "get_player_snapshot", _spy)
        harness.ask_v2("Who is Salah?", bootstrap, team_id=None)

        assert seen["bootstrap"] is bootstrap

    def test_answer_text_unaffected_by_team_id_being_none_vs_omitted(self, bootstrap):
        from fpl_grounded_assistant import harness

        omitted = harness.ask_v2("Who is Salah?", bootstrap)
        explicit_none = harness.ask_v2("Who is Salah?", bootstrap, team_id=None)
        assert omitted["answer_text"] == explicit_none["answer_text"]


# ===========================================================================
# C. AskRequest — optional team_id field
# ===========================================================================

class TestAskRequestTeamIdField:
    def test_defaults_to_none(self):
        from fpl_server import AskRequest
        body = AskRequest(question="test")
        assert body.team_id is None

    def test_accepts_an_integer(self):
        from fpl_server import AskRequest
        body = AskRequest(question="test", team_id=12345)
        assert body.team_id == 12345

    def test_rejects_non_integer(self):
        from fpl_server import AskRequest
        with pytest.raises(Exception):
            AskRequest(question="test", team_id="not-an-int")

    def test_independent_of_squad_context(self):
        # team_id and squad_context are two unrelated per-turn fields — i39
        # does not touch squad_context or its adapter-side handling.
        from fpl_server import AskRequest
        body = AskRequest(question="test", team_id=12345, squad_context={"itb": 5})
        assert body.team_id == 12345
        assert body.squad_context == {"itb": 5}


# ===========================================================================
# D. fpl_server POST /ask — threads req.team_id into ask_v2()
# ===========================================================================

class TestHttpThreadsTeamIdToAskV2:
    def test_team_id_reaches_ask_v2(self, bootstrap, monkeypatch):
        import fpl_server
        from fastapi.testclient import TestClient
        from fpl_grounded_assistant import harness

        seen: dict[str, Any] = {}
        real_ask_v2 = harness.ask_v2

        def _spy(*args, **kwargs):
            seen["team_id"] = kwargs.get("team_id")
            return real_ask_v2(*args, **kwargs)

        monkeypatch.setattr(harness, "ask_v2", _spy)
        fpl_server._init_bootstrap(bootstrap)
        response = TestClient(fpl_server.app).post(
            "/ask",
            json={"question": "Who is Salah?", "team_id": 12345},
            headers={"X-User-Id": "team-id-wiring", "X-User-Tier": "premium"},
        )
        assert response.status_code == 200
        assert seen["team_id"] == 12345

    def test_omitted_team_id_reaches_ask_v2_as_none(self, bootstrap, monkeypatch):
        import fpl_server
        from fastapi.testclient import TestClient
        from fpl_grounded_assistant import harness

        seen: dict[str, Any] = {}
        real_ask_v2 = harness.ask_v2

        def _spy(*args, **kwargs):
            seen["team_id"] = kwargs.get("team_id")
            return real_ask_v2(*args, **kwargs)

        monkeypatch.setattr(harness, "ask_v2", _spy)
        fpl_server._init_bootstrap(bootstrap)
        response = TestClient(fpl_server.app).post(
            "/ask",
            json={"question": "Who is Salah?"},
            headers={"X-User-Id": "team-id-wiring-anon", "X-User-Tier": "premium"},
        )
        assert response.status_code == 200
        assert seen["team_id"] is None
