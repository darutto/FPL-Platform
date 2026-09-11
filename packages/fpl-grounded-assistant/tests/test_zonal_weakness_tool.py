"""
Tests for T2b — get_zonal_weakness / get_zonal_opportunity orchestrator tools.

Integration-level: verifies both tools are registered and runnable via
run_tool against a fixture tactical store (FPL_TACTICAL_ROOT → tmp dir),
that the LLM-facing schemas are in the registry, that team aliases bridge
from FPL bootstrap names to Understat store names, that the store-less path
degrades to missing_context, and that the atomic-tool pattern holds (no
intent mapping, not in SUPPORTED_INTENTS).
"""
from __future__ import annotations

import os as _os
import sys as _sys

import pandas as pd
import pytest

# sys.path bootstrap (mirror fpl_server.py's _SIB pattern) so the full package
# graph imports — zonal_weakness_tool registers in TOOL_REGISTRY on import.
_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PKG = _os.path.dirname(_HERE)
_PKGS = _os.path.dirname(_PKG)
for _p in [
    _PKG,
    _os.path.join(_PKGS, "fpl-api-client"),
    _os.path.join(_PKGS, "fpl-data-core"),
    _os.path.join(_PKGS, "fpl-player-registry"),
    _os.path.join(_PKGS, "fpl-query-tools"),
    _os.path.join(_PKGS, "fpl-tool-contract"),
    _os.path.join(_PKGS, "fpl-tool-runner"),
    _os.path.join(_PKGS, "fpl-captain-engine"),
]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import fpl_grounded_assistant  # noqa: E402  (triggers tool self-registration)
from fpl_tool_runner import run_tool  # noqa: E402
from fpl_grounded_assistant.tool_schema_registry import (  # noqa: E402
    TOOL_NAMES,
    get_tool_schema,
)
from fpl_grounded_assistant.dispatcher import (  # noqa: E402
    SUPPORTED_INTENTS,
    _TOOL_TO_INTENT,
)
from fpl_grounded_assistant.zonal_weakness import CURRENT_SEASON  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture store + bootstrap
# ---------------------------------------------------------------------------

def _row(conceding, shooting, x, y, xg, *, match_id=1, player="Someone"):
    return {
        "season": CURRENT_SEASON, "match_id": match_id, "date": "2025-09-01T15:00:00",
        "shooting_team": shooting, "conceding_team": conceding,
        "player": player, "is_home_shot": True, "minute": 10,
        "x": x, "y": y, "xg": xg, "situation": "Open Play",
        "shot_type": "Right Foot", "result": "Saved Shot",
    }


def _store_df() -> pd.DataFrame:
    """Crystal Palace very weak in-box/right; 'Right Poacher' operates there."""
    rows = []
    for _ in range(10):  # >= MIN_PLAYER_SHOTS for the opportunity matcher
        rows.append(_row("Crystal Palace", "Burnley", 0.90, 0.20, 0.10,
                         match_id=1, player="Right Poacher"))
    rows += [
        _row("Aston Villa", "Crystal Palace", 0.90, 0.20, 0.10, match_id=2),
        _row("Burnley", "Aston Villa", 0.90, 0.20, 0.10, match_id=3),
        _row("Sunderland", "Burnley", 0.90, 0.20, 0.10, match_id=4),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def tactical_store(tmp_path, monkeypatch):
    """Point FPL_TACTICAL_ROOT at a tmp store holding the fixture parquet."""
    season_dir = tmp_path / "seasons" / CURRENT_SEASON
    season_dir.mkdir(parents=True)
    _store_df().to_parquet(season_dir / "understat_shots.parquet", index=False)
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def empty_store(tmp_path, monkeypatch):
    """FPL_TACTICAL_ROOT with no parquet at all."""
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


def _bootstrap() -> dict:
    return {
        "teams": [
            {"id": 1, "name": "Crystal Palace", "short_name": "CRY"},
            {"id": 2, "name": "Aston Villa",    "short_name": "AVL"},
            {"id": 3, "name": "Burnley",        "short_name": "BUR"},
            {"id": 4, "name": "Sunderland",     "short_name": "SUN"},
        ],
        "events": [{"id": 1, "is_current": True}],
    }


# ---------------------------------------------------------------------------
# Registration + schema
# ---------------------------------------------------------------------------

def test_both_tools_have_registry_schemas():
    assert "get_zonal_weakness" in TOOL_NAMES
    assert "get_zonal_opportunity" in TOOL_NAMES
    for name in ("get_zonal_weakness", "get_zonal_opportunity"):
        schema = get_tool_schema(name)
        # descriptions must carry the language-discipline marker
        assert "never buy/sell" in schema.description


def test_atomic_pattern_no_intent_no_classifier():
    # weakness + outlook stay atomic (text-narrated, no intent mapping)
    assert "get_zonal_weakness" not in _TOOL_TO_INTENT
    assert "get_player_zonal_outlook" not in _TOOL_TO_INTENT
    # T4b partial promotion: opportunity is renderable (card) but stays out
    # of the deterministic classifier universe
    assert _TOOL_TO_INTENT["get_zonal_opportunity"] == "zonal_opportunity"
    joined = " ".join(SUPPORTED_INTENTS)
    assert "zonal" not in joined


# ---------------------------------------------------------------------------
# run_tool — happy paths
# ---------------------------------------------------------------------------

def test_run_tool_weakness_ok_shape(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["team"] == "Crystal Palace"
    assert {"zone", "xga_per_game", "league_avg", "delta_vs_avg", "rank"} <= set(out["zones"][0])
    assert out["weakest_zones"][0]["zone"] == "in-box / right"
    assert out["weakest_zones"][0]["delta_vs_avg"] > 0
    assert isinstance(out["verdict"], str) and out["verdict"]


def test_run_tool_weakness_resolves_alias_via_bootstrap(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "CRY"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["team"] == "Crystal Palace"


def test_run_tool_opportunity_ok_shape(tactical_store):
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert out["opponent"] == "Crystal Palace"
    zones = {o["zone"]: o for o in out["opportunities"]}
    assert "in-box / right" in zones
    assert "Right Poacher" in zones["in-box / right"]["players"]


# ---------------------------------------------------------------------------
# T4b — wrapper enrichment of the exploiter table (team_short / position)
# ---------------------------------------------------------------------------

def _bootstrap_with_elements() -> dict:
    """Bootstrap whose elements match 'Right Poacher' by full name."""
    bs = _bootstrap()
    bs["elements"] = [
        {"first_name": "Right", "second_name": "Poacher",
         "web_name": "Poacher", "element_type": 3},
    ]
    return bs


def test_run_tool_opportunity_exploiters_enriched_matched_player(tactical_store):
    out = run_tool(
        "get_zonal_opportunity", {"opponent": "Crystal Palace"},
        _bootstrap_with_elements(),
    )
    assert out["status"] == "ok"
    exploiters = out["exploiters"]
    assert exploiters, "fixture store should yield at least one exploiter"
    top = exploiters[0]
    assert top["rank"] == 1
    assert top["player"] == "Right Poacher"
    assert top["web_name"] == "Poacher"          # FPL join hit
    assert top["position"] == "MID"
    assert top["team_short"] == "BUR"            # inverted Understat bridge
    assert top["fit_score"] == 10.0              # best cross of this answer


def test_run_tool_opportunity_exploiters_unmatched_player_degrades(tactical_store):
    # No elements in bootstrap → the fragile name join misses; the player is
    # kept with the store name and an empty position, never dropped.
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    top = out["exploiters"][0]
    assert top["player"] == "Right Poacher"
    assert top["web_name"] == "Right Poacher"
    assert top["position"] == ""
    assert top["team_short"] == "BUR"


def test_run_tool_opportunity_card_fields_present(tactical_store):
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    assert [z["lateral"] for z in out["zones"]] == ["left", "central", "right"]
    for z in out["zones"]:
        assert z["opportunity_level"] in ("opp", "warm", "cool")
    assert out["weakness_label"] == "Débil dentro del área"
    assert "penalty_xga_per_game" in out["penalty_context"]
    assert isinstance(out["verdict"], str) and out["verdict"]
    # language discipline: opportunity framing only
    for banned in ("ficha", "vende", "compra"):
        assert banned not in out["verdict"].lower()


# ---------------------------------------------------------------------------
# team filter (i85) — bootstrap-side resolution (short_name/alias -> store
# team name via _to_store_team, same bridge as `opponent`)
# ---------------------------------------------------------------------------

def test_run_tool_opportunity_team_filter_resolves_via_short_name(tactical_store):
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "BUR"},
        _bootstrap(),
    )
    assert out["status"] == "ok"
    # i87: team-scoped gates rank the whole team -- "Someone" (1 shot,
    # in-box/right, for Burnley in _store_df) now appears, labelled thin.
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher", "Someone"]
    assert out["exploiters"][1]["sample"] == "thin"
    # the handler resolves "BUR" -> "Burnley" via _to_store_team before the
    # engine ever sees it, so team_filter["requested"] echoes the resolved
    # store name, same as the engine received -- not the raw user input.
    assert out["team_filter"]["requested"] == "Burnley"
    assert out["team_filter"]["matched"] == "Burnley"
    assert out["team_filter"]["source"] == "explicit"


def test_run_tool_opportunity_team_filter_unresolved_message(tactical_store):
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "Real Madrid"},
        _bootstrap(),
    )
    assert out["status"] == "ok"
    assert out["exploiters"] == []
    assert out["team_filter"]["matched"] is None
    assert "message" in out and "Real Madrid" in out["message"]


def test_run_tool_opportunity_no_team_key_when_omitted(tactical_store):
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert "team_filter" not in out


# ---------------------------------------------------------------------------
# i86 — deterministic subject-team inference when the model omits `team`.
# The i85 parameter is correct when passed; measured live 2026-09-11 the
# orchestrator still dispatched "¿Qué jugadores de liverpool pueden explotar
# las zonas débiles del Fulham?" as {opponent: Fulham} with no `team`. The
# handler therefore reads the user's question (bootstrap["_question"], put
# there by ask_orchestrated) and backfills `team` when exactly one other
# team is named. It must never invent a filter from an ambiguous question.
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.zonal_weakness_tool import (  # noqa: E402
    _QUESTION_KEY,
    _mentioned_teams,
    infer_subject_team,
)


def test_question_key_matches_orchestrator_constant():
    """The tool spells the key itself (no orchestrator import from a tool
    module); this is what stops the two spellings drifting apart."""
    from fpl_grounded_assistant.orchestrator import QUESTION_CONTEXT_KEY
    assert _QUESTION_KEY == QUESTION_CONTEXT_KEY


class TestMentionedTeams:
    def test_bootstrap_names_match_as_whole_phrases_case_insensitive(self):
        found = _mentioned_teams("jugadores de burnley contra el Crystal Palace", _bootstrap())
        assert {t["short_name"] for t in found} == {"BUR", "CRY"}

    def test_alias_resolves_through_shared_resolver(self):
        # "villa" is an alias -> AVL; "palace" is an alias -> CRY
        found = _mentioned_teams("que jugadores del villa explotan al palace", _bootstrap())
        assert {t["short_name"] for t in found} == {"AVL", "CRY"}

    def test_uppercase_short_code_matches(self):
        found = _mentioned_teams("jugadores de BUR vs Crystal Palace", _bootstrap())
        assert {t["short_name"] for t in found} == {"BUR", "CRY"}

    def test_lowercase_short_code_does_not_match(self):
        # "sun" is an ordinary word; SUN the code must only match in caps
        found = _mentioned_teams("the sun was out at Crystal Palace", _bootstrap())
        assert {t["short_name"] for t in found} == {"CRY"}

    def test_partial_word_does_not_match(self):
        # "Burnleyville" must not surface Burnley
        found = _mentioned_teams("Burnleyville hosts Crystal Palace", _bootstrap())
        assert {t["short_name"] for t in found} == {"CRY"}


class TestInferSubjectTeam:
    def test_one_other_team_is_the_subject(self):
        q = "Que jugadores de burnley pueden explotar las zonas debiles del Crystal Palace?"
        assert infer_subject_team(q, "Crystal Palace", _bootstrap()) == "BUR"

    def test_only_opponent_named_infers_nothing(self):
        q = "Que jugadores pueden explotar las zonas debiles del Crystal Palace?"
        assert infer_subject_team(q, "Crystal Palace", _bootstrap()) is None

    def test_two_other_teams_is_ambiguous_infers_nothing(self):
        q = "jugadores de burnley o del sunderland contra el crystal palace"
        assert infer_subject_team(q, "Crystal Palace", _bootstrap()) is None

    def test_opponent_named_by_alias_is_still_excluded(self):
        # the model passed "CRY"; the question says "palace" -- same team,
        # must not be mistaken for a second, subject team
        q = "jugadores de burnley contra el palace"
        assert infer_subject_team(q, "CRY", _bootstrap()) == "BUR"

    def test_unresolvable_opponent_infers_nothing(self):
        # every mention could be the opponent under another name; don't guess
        q = "jugadores de burnley contra el Nadie FC"
        assert infer_subject_team(q, "Nadie FC", _bootstrap()) is None

    def test_empty_question_infers_nothing(self):
        assert infer_subject_team("", "Crystal Palace", _bootstrap()) is None


def _bootstrap_with_question(question: str) -> dict:
    bs = dict(_bootstrap())
    bs[_QUESTION_KEY] = question
    return bs


def test_run_tool_opportunity_backfills_team_from_question(tactical_store):
    """THE production repro: the model passes only `opponent`, the question
    names one other team -> the handler filters to it anyway."""
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace"},  # model forgot `team`
        _bootstrap_with_question(
            "Que jugadores de burnley pueden explotar las zonas debiles del Crystal Palace?"
        ),
    )
    assert out["status"] == "ok"
    # i87: team-scoped gates rank the whole team -- "Someone" (1 shot,
    # in-box/right, for Burnley in _store_df) now appears, labelled thin.
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher", "Someone"]
    assert out["exploiters"][1]["sample"] == "thin"
    assert out["team_filter"]["requested"] == "Burnley"
    assert out["team_filter"]["matched"] == "Burnley"
    assert out["team_filter"]["source"] == "inferred"


def test_run_tool_opportunity_explicit_team_beats_inference(tactical_store):
    """When the model DID pass `team`, the question is not consulted -- an
    explicit argument is never second-guessed by the heuristic."""
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "BUR"},
        _bootstrap_with_question(
            "jugadores del sunderland contra el crystal palace"  # names a DIFFERENT team
        ),
    )
    assert out["team_filter"]["matched"] == "Burnley"
    assert out["team_filter"]["source"] == "explicit"


def test_run_tool_opportunity_no_inference_without_question_context(tactical_store):
    """No `_question` in the bootstrap (deterministic routes, direct callers)
    -> behaviour is exactly the pre-i86 unfiltered path."""
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert "team_filter" not in out


def test_run_tool_opportunity_ambiguous_question_stays_unfiltered(tactical_store):
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace"},
        _bootstrap_with_question(
            "jugadores de burnley o del sunderland contra el crystal palace"
        ),
    )
    assert out["status"] == "ok"
    assert "team_filter" not in out  # never invent a filter from an ambiguous question


# ---------------------------------------------------------------------------
# run_tool — degraded paths (never raise into the orchestrator)
# ---------------------------------------------------------------------------

def test_run_tool_weakness_not_found(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "Real Madrid"}, _bootstrap())
    assert out["status"] == "not_found"
    assert "message" in out


def test_run_tool_missing_context_when_no_store(empty_store):
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "missing_context"
    assert "message" in out
    out2 = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert out2["status"] == "missing_context"


def test_run_tool_blank_team_is_not_found(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "  "}, _bootstrap())
    assert out["status"] == "not_found"
    # a missing REQUIRED arg is rejected by the runner's schema validation
    # before the handler runs — still a structured status, never a raise
    out2 = run_tool("get_zonal_opportunity", {}, _bootstrap())
    assert out2["status"] == "error"


# ---------------------------------------------------------------------------
# get_player_zonal_outlook (T-player)
# ---------------------------------------------------------------------------

def _bootstrap_with_fixtures() -> dict:
    """Bootstrap with a current GW and team_fixtures: Burnley (id 3, home of
    'Right Poacher' in the fixture store) faces Crystal Palace in GW1 and
    Sunderland in GW2."""
    bs = _bootstrap()
    bs["events"] = [{"id": 1, "is_current": True}]
    bs["team_fixtures"] = {
        3: [
            {"gameweek": 1, "opponent_team": 1, "is_home": True},
            {"gameweek": 2, "opponent_team": 4, "is_home": False},
            {"gameweek": 9, "opponent_team": 2, "is_home": True},  # outside horizon
        ],
    }
    return bs


class TestPlayerZonalOutlook:
    def test_run_tool_outlook_ok_shape(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher", "horizon": 2},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "ok"
        assert out["player"] == "Right Poacher"
        assert out["team"] == "Burnley"
        gws = [e["gameweek"] for e in out["outlook"]]
        assert gws == [1, 2]  # GW9 fixture is outside the horizon
        by_gw = {e["gameweek"]: e for e in out["outlook"]}
        assert by_gw[1]["opponent"] == "Crystal Palace"
        assert by_gw[1]["status"] == "favorable"
        assert by_gw[1]["matches"][0]["zone"] == "in-box / right"
        assert isinstance(out["verdict"], str) and out["verdict"]

    def test_run_tool_outlook_horizon_clamped(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher", "horizon": 99},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "ok"  # clamped to MAX, not an error

    def test_run_tool_outlook_player_not_found(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook", {"player": "Nobody"}, _bootstrap_with_fixtures()
        )
        assert out["status"] == "not_found"
        assert "message" in out

    def test_run_tool_outlook_missing_fixtures(self, tactical_store):
        out = run_tool(
            "get_player_zonal_outlook", {"player": "Right Poacher"}, _bootstrap()
        )
        assert out["status"] == "missing_context"
        assert "message" in out

    def test_run_tool_outlook_missing_store(self, empty_store):
        out = run_tool(
            "get_player_zonal_outlook",
            {"player": "Right Poacher"},
            _bootstrap_with_fixtures(),
        )
        assert out["status"] == "missing_context"


# ---------------------------------------------------------------------------
# T4b — DefensiveZonesMeta extraction (zonal_opportunity renderable intent)
# ---------------------------------------------------------------------------

class TestDefensiveZonesMeta:
    def _ok_output(self, tactical_store) -> dict:
        return run_tool(
            "get_zonal_opportunity", {"opponent": "Crystal Palace"},
            _bootstrap_with_elements(),
        )

    def test_meta_extracted_on_ok(self, tactical_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        meta = _extract_structured_meta(
            "zonal_opportunity", self._ok_output(tactical_store), "ok"
        )
        zo = meta["zonal_opportunity"]
        assert zo is not None
        assert zo.opponent == "Crystal Palace"
        assert zo.weakness_label == "Débil dentro del área"
        assert len(zo.zones) == 3
        assert [z.lateral for z in zo.zones] == ["left", "central", "right"]
        assert all(z.opportunity_level in ("opp", "warm", "cool") for z in zo.zones)
        assert zo.exploiters and zo.exploiters[0].rank == 1
        assert zo.exploiters[0].web_name == "Poacher"
        assert zo.exploiters[0].team_short == "BUR"
        assert zo.exploiters[0].position == "MID"
        assert zo.exploiters[0].fit_score == 10.0
        assert zo.ai_active is True
        # every other structured field stays None on this intent
        assert meta["differential"] is None and meta["comparison"] is None

    def test_meta_none_on_non_ok_outcome(self, tactical_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        out = run_tool("get_zonal_opportunity", {"opponent": "Real Madrid"}, _bootstrap())
        assert out["status"] == "not_found"
        meta = _extract_structured_meta("zonal_opportunity", out, "not_found")
        assert meta["zonal_opportunity"] is None

    def test_meta_none_on_missing_context(self, empty_store):
        from fpl_grounded_assistant.final_response import _extract_structured_meta

        out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
        assert out["status"] == "missing_context"
        meta = _extract_structured_meta("zonal_opportunity", out, "missing_context")
        assert meta["zonal_opportunity"] is None

    def test_meta_none_on_pre_enrichment_payload(self):
        # A stale payload without the T4b "zones" field must not render a
        # half-empty card.
        from fpl_grounded_assistant.final_response import (
            _extract_zonal_opportunity_meta,
        )

        legacy = {"status": "ok", "opponent": "Crystal Palace", "opportunities": []}
        assert _extract_zonal_opportunity_meta(legacy) is None

    def test_finalresponse_has_zonal_opportunity_field(self):
        import dataclasses

        from fpl_grounded_assistant.final_response import FinalResponse

        names = {f.name for f in dataclasses.fields(FinalResponse)}
        assert "zonal_opportunity" in names


# ---------------------------------------------------------------------------
# i86 end-to-end: through ask_orchestrated() with a mocked provider that
# omits `team` -- the exact production shape. Proves the orchestrator really
# exposes the question to the handler (not just that the handler would use
# it if given), and that the caller's bootstrap is not mutated to do so.
# ---------------------------------------------------------------------------

class _ForgetfulClient:
    """Anthropic-shaped client: first call requests get_zonal_opportunity
    with ONLY `opponent` (as the live orchestrator did), then plain text."""

    def __init__(self) -> None:
        self.messages = self
        self._calls = 0

    def create(self, **kwargs):
        self._calls += 1
        if self._calls == 1:
            block = type("_TB", (), {
                "type": "tool_use", "id": "toolu_0",
                "name": "get_zonal_opportunity",
                "input": {"opponent": "Crystal Palace"},
            })()
            return type("_R", (), {"content": [block], "stop_reason": "tool_use"})()
        txt = type("_T", (), {"type": "text", "text": "synth"})()
        return type("_R", (), {"content": [txt], "stop_reason": "end_turn"})()


def test_orchestrated_question_reaches_handler_and_backfills_team(
    tactical_store, monkeypatch
):
    monkeypatch.setenv("FPL_ORCH_TEST_INJECTION", "1")
    from fpl_grounded_assistant.orchestrator import ask_orchestrated

    caller_bootstrap = _bootstrap()
    before = dict(caller_bootstrap)

    res = ask_orchestrated(
        "Que jugadores de burnley pueden explotar las zonas debiles del Crystal Palace?",
        caller_bootstrap,
        client=_ForgetfulClient(),
        _eval_client=None,
    )

    assert res.tool_chosen == "get_zonal_opportunity"
    assert res.tool_args == {"opponent": "Crystal Palace"}   # model's args untouched
    assert res.tool_output["status"] == "ok"
    assert [e["player"] for e in res.tool_output["exploiters"]] == ["Right Poacher", "Someone"]
    assert res.tool_output["team_filter"]["matched"] == "Burnley"
    assert res.tool_output["team_filter"]["source"] == "inferred"
    # the shared bootstrap the caller handed in is byte-for-byte unchanged
    assert caller_bootstrap == before
    assert "_question" not in caller_bootstrap


# ---------------------------------------------------------------------------
# i87 — the card projection carries the team scope and per-player evidence,
# so a UI/user can see WHY the table looks the way it does (found 2026-09-11:
# team_filter was invisible in the zonal_opportunity payload, so a correctly
# scoped-but-empty table was indistinguishable from "the fix didn't fire").
# ---------------------------------------------------------------------------

def test_card_projection_carries_team_filter_and_evidence(tactical_store):
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "BUR"},
        _bootstrap(),
    )
    meta = _extract_zonal_opportunity_meta(out)
    assert meta is not None
    assert meta.team_filter is not None
    assert meta.team_filter.matched == "Burnley"
    assert meta.team_filter.source == "explicit"
    assert meta.team_filter.min_shots == 1
    top = meta.exploiters[0]
    assert top.n_shots == 10
    assert top.sample == "ok"
    assert top.zone_share == 1.0


def test_card_projection_unscoped_has_no_team_filter(tactical_store):
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    meta = _extract_zonal_opportunity_meta(out)
    assert meta is not None
    assert meta.team_filter is None
