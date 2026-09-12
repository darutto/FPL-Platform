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
    # outlook stays atomic (text-narrated, no intent mapping)
    assert "get_player_zonal_outlook" not in _TOOL_TO_INTENT
    # T4b partial promotion: opportunity is renderable (card) but stays out
    # of the deterministic classifier universe
    assert _TOOL_TO_INTENT["get_zonal_opportunity"] == "zonal_opportunity"
    # i91: a pure "zonas débiles" question (no players/exploiting mentioned)
    # gets the SAME card intent -- the card just renders without an
    # exploiter table (DefensiveZonesMeta.has_exploiters distinguishes the
    # two). This inverts the pre-i91 "weakness stays atomic" policy on
    # purpose: the pitch view never depended on player data to begin with.
    assert _TOOL_TO_INTENT["get_zonal_weakness"] == "zonal_opportunity"
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
    _team_args,
    infer_subject_team,
    infer_subject_teams,
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


def test_run_tool_opportunity_two_named_teams_scope_to_both(tactical_store):
    """i89 supersedes i86's "two teams is ambiguous": two named teams is a
    two-team scope, ranked together, each row carrying its team."""
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace"},
        _bootstrap_with_question(
            "jugadores de burnley o del villa contra el crystal palace"
        ),
    )
    assert out["status"] == "ok"
    tf = out["team_filter"]
    assert tf["source"] == "inferred"
    assert tf["matched_teams"] == ["Burnley", "Aston Villa"]
    assert tf["unmatched_teams"] == []
    assert tf["matched"] == "Burnley, Aston Villa"
    # both teams are the scope; only Burnley has a player in the fixture
    # store (the lone Villa shot belongs to "Someone", whose team resolves
    # to Burnley by last-shot), so the table is Burnley-only but the scope
    # is not.
    teams = {e["team"] for e in out["exploiters"]}
    assert teams == {"Burnley"}


def test_run_tool_opportunity_alternative_rival_phrasing_scopes_to_named_teams(tactical_store):
    """#251 review objection: "Brighton o Fulham, cual es mejor para atacar
    con el Arsenal?" reads on the surface as picking BETWEEN two rivals, not
    naming two attacking teams. i89's decided policy (this test documents,
    not decides, it) is that EVERY named team becomes the scope regardless
    of that surface grammar -- inverting i86 (2+ mentions == ambiguous ==
    fall back to the whole league). This is accepted because it is visible:
    ``team_filter.source == "inferred"`` and ``matched_teams`` names exactly
    who was scoped, so a caller can always see why those teams appeared
    rather than the question silently degrading to a league-wide table.
    """
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace"},
        _bootstrap_with_question(
            "Crystal Palace o del villa, cual es mejor para atacar con el burnley?"
        ),
    )
    assert out["status"] == "ok"
    tf = out["team_filter"]
    assert tf["source"] == "inferred"
    assert tf["matched_teams"] == ["Aston Villa", "Burnley"]
    assert tf["unmatched_teams"] == []


@pytest.fixture
def three_team_scope_store(tmp_path, monkeypatch):
    """Wolves: 6 qualifying candidates. Burnley: 2 (matches the existing
    'Right Poacher' + 'Someone' fixture shape). Aston Villa: 0 (only ever
    concedes in this store, never shoots) -- so a per-team cap test can
    assert 3 + 2 + 0 without inventing a fourth store shape."""
    rows = []
    for _ in range(10):
        rows.append(_row("Crystal Palace", "Burnley", 0.90, 0.20, 0.10,
                         match_id=1, player="Right Poacher"))
    rows.append(_row("Sunderland", "Burnley", 0.90, 0.20, 0.10,
                      match_id=4, player="Someone"))
    # Crystal Palace's own shot conceded by Aston Villa -- a distinct player
    # name from the "Someone" default so it doesn't merge into Burnley's
    # "Someone" via compute_player_zone_shares' last-shot team resolution.
    rows.append(_row("Aston Villa", "Crystal Palace", 0.90, 0.20, 0.10,
                      match_id=2, player="Palace Nobody"))
    # Aston Villa needs a real shooting_team row to resolve as a matched
    # team at all -- against Sunderland (not Crystal Palace, so it doesn't
    # perturb Crystal Palace's own weak-zone computation) and placed in
    # in-box/left (not Crystal Palace's weak zone) so it contributes zero
    # opportunity candidates, not zero rows in the store.
    rows.append(_row("Sunderland", "Aston Villa", 0.90, 0.90, 0.05,
                      match_id=20, player="Villa Nobody"))
    for i in range(6):
        rows.append(_row("Crystal Palace", "Wolves", 0.90, 0.20, 0.10,
                          match_id=10 + i, player=f"Wolf {i}"))
    season_dir = tmp_path / "seasons" / CURRENT_SEASON
    season_dir.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(season_dir / "understat_shots.parquet", index=False)
    monkeypatch.setenv("FPL_TACTICAL_ROOT", str(tmp_path))
    return tmp_path


def test_run_tool_opportunity_three_teams_caps_per_team_not_globally(three_team_scope_store):
    """i90 A1: with 2+ matched teams the old global top-5 cut could starve a
    named team down to zero rows just because its best fit ranked below the
    global cut. Cap becomes up to TOP_EXPLOITERS_PER_TEAM (3) per team,
    TOP_EXPLOITERS_MULTI (15) overall -- so 6/2/0 candidates become 3/2/0
    rows, and ``candidates_per_team`` reports the true counts (6/2/0), not
    the post-cap row counts, so a caller can tell "capped" from "no fit"."""
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": ["Wolves", "Burnley", "Aston Villa"]},
        _bootstrap(),
    )
    assert out["status"] == "ok"
    tf = out["team_filter"]
    assert tf["matched_teams"] == ["Wolves", "Burnley", "Aston Villa"]
    by_team: dict[str, int] = {}
    for e in out["exploiters"]:
        by_team[e["team"]] = by_team.get(e["team"], 0) + 1
    assert by_team == {"Wolves": 3, "Burnley": 2}
    assert tf["candidates_per_team"] == {"Wolves": 6, "Burnley": 2, "Aston Villa": 0}


def test_run_tool_opportunity_single_team_shape_unchanged_by_a1(three_team_scope_store):
    """0-1 matched teams: A1's per-team cap must never engage -- pins the
    exact pre-i90 single-team shape (same rows, no ``candidates_per_team``),
    which is what makes the PR's "byte-identical, pinned" claim true for
    that case (see #251 body correction)."""
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "Burnley"},
        _bootstrap(),
    )
    assert [e["player"] for e in out["exploiters"]] == ["Right Poacher", "Someone"]
    assert "candidates_per_team" not in out["team_filter"]


# ---------------------------------------------------------------------------
# i90 — fixture-derived default scope (wrapper level). "Zonas debiles de
# Crystal Palace?" with no team named defaulted to a league-wide ranking,
# blind to who actually plays them soon. Without `team`/`teams` AND without
# an inferable team from the question, the handler now scopes to whoever
# faces the opponent in the fixture window (reusing the exact
# `fixtures_for_team` bridge the outlook tool already uses).
# ---------------------------------------------------------------------------

def _bootstrap_with_cry_fixtures() -> dict:
    """Crystal Palace (id 1, the opponent) faces Burnley (id 3) at home in
    GW1 and Aston Villa (id 2) away in GW2 -- both inside the default
    5-GW horizon from current_gw=1."""
    bs = _bootstrap()
    bs["events"] = [{"id": 1, "is_current": True}]
    bs["team_fixtures"] = {
        1: [
            {"gameweek": 1, "opponent_team": 3, "is_home": True},
            {"gameweek": 2, "opponent_team": 2, "is_home": False},
        ],
    }
    return bs


class TestFixtureScopedDefault:
    def test_no_team_no_inference_scopes_to_fixtures(self, tactical_store):
        out = run_tool(
            "get_zonal_opportunity",
            {"opponent": "Crystal Palace"},
            _bootstrap_with_cry_fixtures(),
        )
        assert out["status"] == "ok"
        tf = out["team_filter"]
        assert tf["source"] == "fixtures"
        assert tf["matched_teams"] == ["Burnley", "Aston Villa"]
        assert tf["scheduled_opponents"] == ["Burnley", "Aston Villa"]
        assert tf["requested_teams"] == []
        assert tf["requested"] is None
        assert tf["fixture_window"]["from_gw"] == 1
        assert tf["fixture_window"]["to_gw"] == 2
        # Palace at home vs Burnley (GW1) -> Burnley is away
        burnley_rows = [e for e in out["exploiters"] if e["team"] == "Burnley"]
        assert burnley_rows and burnley_rows[0]["gameweek"] == 1
        assert burnley_rows[0]["is_home"] is False

    def test_explicit_team_still_beats_fixtures(self, tactical_store):
        """A named team must never be silently overridden by the fixture
        calendar -- explicit scope takes precedence, unconditionally."""
        out = run_tool(
            "get_zonal_opportunity",
            {"opponent": "Crystal Palace", "team": "BUR"},
            _bootstrap_with_cry_fixtures(),
        )
        assert out["team_filter"]["source"] == "explicit"
        assert "fixture_window" not in out["team_filter"]

    def test_empty_fixture_window_falls_back_to_league_with_message(self, tactical_store):
        bs = _bootstrap()
        bs["events"] = [{"id": 1, "is_current": True}]
        bs["team_fixtures"] = {1: []}  # Crystal Palace has no fixtures in window
        out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, bs)
        assert out["status"] == "ok"
        assert out["team_filter"]["source"] is None
        assert "message" in out and "toda la liga" in out["message"]
        assert out["team_filter"]["matched_teams"] == []

    def test_no_team_fixtures_in_bootstrap_falls_back_to_league_with_message(self, tactical_store):
        out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
        assert out["status"] == "ok"
        assert "team_filter" not in out
        assert "message" in out and "toda la liga" in out["message"]

    def test_horizon_argument_clamped_and_narrows_window(self, tactical_store):
        out = run_tool(
            "get_zonal_opportunity",
            {"opponent": "Crystal Palace", "horizon": 1},
            _bootstrap_with_cry_fixtures(),
        )
        # horizon=1 -> window is just [current_gw, current_gw+1) -> GW1 only
        assert out["team_filter"]["matched_teams"] == ["Burnley"]
        assert out["team_filter"]["fixture_window"] == {"from_gw": 1, "to_gw": 1, "horizon": 1}

        out_over = run_tool(
            "get_zonal_opportunity",
            {"opponent": "Crystal Palace", "horizon": 99},
            _bootstrap_with_cry_fixtures(),
        )
        assert out_over["status"] == "ok"  # clamped to MAX_OUTLOOK_HORIZON, never errors

    def test_end_of_season_window_clips_at_the_wrapper_too(self, tactical_store):
        """The _fixtures_callback window filter (`current_gw <= gw <
        current_gw + horizon`) only ever sees what's actually in
        team_fixtures -- with GW37 current and the season ending at 38,
        horizon=5 must not manufacture GW39-41 fixtures out of nothing."""
        bs = _bootstrap()
        bs["events"] = [{"id": 37, "is_current": True}]
        bs["team_fixtures"] = {
            1: [
                {"gameweek": 37, "opponent_team": 3, "is_home": True},
                {"gameweek": 38, "opponent_team": 2, "is_home": False},
            ],
        }
        out = run_tool(
            "get_zonal_opportunity", {"opponent": "Crystal Palace", "horizon": 5}, bs,
        )
        assert out["status"] == "ok"
        fw = out["team_filter"]["fixture_window"]
        assert fw["from_gw"] == 37
        assert fw["to_gw"] == 38
        assert out["team_filter"]["matched_teams"] == ["Burnley", "Aston Villa"]


# ---------------------------------------------------------------------------
# i90 — name-bridge coverage, both directions. test_name_resolution.py
# already pins short_name -> _SHORT_TO_UNDERSTAT (every current team code
# has a store-name entry); i90's fixture scope goes the OTHER way too --
# the callback hands back store team names (e.g. from
# ``understat_shots.parquet["shooting_team"]``) that then need to resolve
# BACK to a short_name for the FPL-side join. A silent gap here is exactly
# the failure this test exists to catch: a real rival showing up in
# ``unmatched_teams`` in prod (see scripts/verify_prod_rollover.py).
# ---------------------------------------------------------------------------

from fpl_grounded_assistant.zonal_weakness_tool import (  # noqa: E402
    _SHORT_TO_UNDERSTAT,
    _UNDERSTAT_TO_SHORT,
)
from test_name_resolution import CURRENT_PL_TEAMS  # noqa: E402


def test_understat_to_short_bridge_covers_all_current_teams():
    missing = [
        code for _name, code, _nick in CURRENT_PL_TEAMS
        if _SHORT_TO_UNDERSTAT.get(code, "").lower() not in _UNDERSTAT_TO_SHORT
    ]
    assert missing == [], f"_UNDERSTAT_TO_SHORT missing entries for: {missing}"


def test_understat_to_short_bridge_is_the_true_inverse():
    """Not just "some inverse exists" -- the SAME short_name round-trips,
    so a store name never resolves back to the wrong FPL team."""
    for code, store_name in _SHORT_TO_UNDERSTAT.items():
        assert _UNDERSTAT_TO_SHORT.get(store_name.lower()) == code


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


# ---------------------------------------------------------------------------
# i91 -- "zonas débiles de X" alone (no players/exploiting mentioned) still
# gets the pitch-view card. The wrapper enriches get_zonal_weakness's own
# output with card_zones/weakness_label/weakness_strength (distinct keys
# from its pre-existing zones/weakest_zones, so nothing that reads those
# changes shape) and the card projection distinguishes it from
# get_zonal_opportunity via the ABSENCE of an "exploiters" key.
# ---------------------------------------------------------------------------

def test_run_tool_weakness_ok_enriches_card_fields(tactical_store):
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    assert out["status"] == "ok"
    # pre-existing contract, unchanged: zones is still the 6-zone list
    assert len(out["zones"]) == 6
    assert {"zone", "xga_per_game", "league_avg", "delta_vs_avg", "rank"} <= set(out["zones"][0])
    # i91 additions, under distinct keys
    assert [z["lateral"] for z in out["card_zones"]] == ["left", "central", "right"]
    assert isinstance(out["weakness_label"], str) and out["weakness_label"]
    assert out["weakness_strength"] in ("clear", "marginal", "none")
    assert "exploiters" not in out  # the absence IS the has_exploiters=False signal


def test_run_tool_weakness_matches_opportunity_card_fields_for_same_team(tactical_store):
    """The shared engine helper means get_zonal_weakness and
    get_zonal_opportunity must agree exactly on the pitch shading and
    label for the same team -- not two independently-computed answers
    that could silently drift apart."""
    weakness_out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    opportunity_out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    assert weakness_out["card_zones"] == opportunity_out["zones"]
    assert weakness_out["weakness_label"] == opportunity_out["weakness_label"]
    assert weakness_out["weakness_strength"] == opportunity_out["weakness_strength"]


def test_card_projection_weakness_only_has_no_exploiter_table(tactical_store):
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool("get_zonal_weakness", {"team": "Crystal Palace"}, _bootstrap())
    meta = _extract_zonal_opportunity_meta(out)
    assert meta is not None
    assert meta.opponent == "Crystal Palace"
    assert meta.has_exploiters is False
    assert meta.exploiters == ()
    assert len(meta.zones) == 3
    assert meta.team_filter is None


def test_card_projection_opportunity_still_has_exploiters_flag_true(tactical_store):
    """Regression pin: get_zonal_opportunity's projection must not flip to
    has_exploiters=False just because this field now exists."""
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool("get_zonal_opportunity", {"opponent": "Crystal Palace"}, _bootstrap())
    meta = _extract_zonal_opportunity_meta(out)
    assert meta.has_exploiters is True


def test_zonal_weakness_maps_to_zonal_opportunity_intent():
    from fpl_grounded_assistant.dispatcher import _TOOL_TO_INTENT
    assert _TOOL_TO_INTENT["get_zonal_weakness"] == "zonal_opportunity"


def test_card_projection_carries_origin_evidence(tactical_store):
    """i88: origin fields reach DefensiveZonesMeta.Exploiter."""
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "team": "BUR"},
        _bootstrap(),
    )
    meta = _extract_zonal_opportunity_meta(out)
    top = meta.exploiters[0]
    assert top.origin == "open_play"        # fixture rows are all Open Play
    assert top.set_piece_share == 0.0
    assert top.zone_shots == 10


# ---------------------------------------------------------------------------
# i89 -- several teams in one scope, and the argument shapes the model may
# send for them. Asked 2026-09-11: "jugadores de arsenal, liverpool y
# manchester city para atacar al brighton" -- one table, three teams.
# ---------------------------------------------------------------------------

class TestTeamArgs:
    def test_single_string(self):
        assert _team_args({"team": "BUR"}) == ["BUR"]

    def test_comma_separated_string(self):
        assert _team_args({"team": "Burnley, Sunderland"}) == ["Burnley", "Sunderland"]

    def test_team_as_list_and_teams_list_dedup(self):
        assert _team_args({"team": ["BUR"], "teams": ["SUN", "BUR"]}) == ["BUR", "SUN"]

    def test_empty_and_blank(self):
        assert _team_args({}) == []
        assert _team_args({"team": " , "}) == []


class TestInferSubjectTeams:
    def test_three_named_teams_in_mention_order(self):
        q = "jugadores de sunderland, burnley y villa para atacar al crystal palace"
        assert infer_subject_teams(q, "Crystal Palace", _bootstrap()) == ["SUN", "BUR", "AVL"]

    def test_single_helper_still_none_on_several(self):
        q = "jugadores de burnley o del sunderland contra el crystal palace"
        assert infer_subject_team(q, "Crystal Palace", _bootstrap()) is None
        assert infer_subject_teams(q, "Crystal Palace", _bootstrap()) == ["BUR", "SUN"]

    def test_unresolvable_opponent_infers_nothing(self):
        assert infer_subject_teams("burnley y sunderland vs nadie", "Nadie FC", _bootstrap()) == []


def test_run_tool_opportunity_explicit_teams_list(tactical_store):
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "teams": ["BUR", "AVL"]},
        _bootstrap(),
    )
    assert out["status"] == "ok"
    assert out["team_filter"]["source"] == "explicit"
    assert out["team_filter"]["matched_teams"] == ["Burnley", "Aston Villa"]


def test_run_tool_opportunity_partial_resolution_proceeds_and_reports(tactical_store):
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "teams": ["BUR", "Real Madrid"]},
        _bootstrap(),
    )
    assert out["status"] == "ok"
    tf = out["team_filter"]
    assert tf["matched_teams"] == ["Burnley"]
    assert tf["unmatched_teams"] == ["Real Madrid"]
    assert [e["player"] for e in out["exploiters"]][:1] == ["Right Poacher"]
    assert "Real Madrid" in out["message"] and "ignored" in out["message"]


def test_card_projection_carries_team_lists_and_strength(tactical_store):
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace", "teams": ["BUR", "AVL"]},
        _bootstrap(),
    )
    meta = _extract_zonal_opportunity_meta(out)
    assert meta.team_filter.matched_teams == ("Burnley", "Aston Villa")
    assert meta.team_filter.unmatched_teams == ()
    assert meta.weakness_strength == "clear"   # fixture: Palace +200% on the right


def test_card_projection_carries_fixture_scope(tactical_store):
    """i90: fixture_window/fixtures/scheduled_opponents/candidates_per_team
    and each exploiter's gameweek/is_home reach the card projection."""
    from fpl_grounded_assistant.final_response import _extract_zonal_opportunity_meta
    out = run_tool(
        "get_zonal_opportunity",
        {"opponent": "Crystal Palace"},
        _bootstrap_with_cry_fixtures(),
    )
    meta = _extract_zonal_opportunity_meta(out)
    tf = meta.team_filter
    assert tf is not None
    assert tf.source == "fixtures"
    assert tf.requested is None
    assert tf.requested_teams == ()
    assert tf.matched_teams == ("Burnley", "Aston Villa")
    assert tf.scheduled_opponents == ("Burnley", "Aston Villa")
    assert tf.fixture_window is not None
    assert (tf.fixture_window.from_gw, tf.fixture_window.to_gw) == (1, 2)
    burnley_fixture = next(f for f in tf.fixtures if f.team == "Burnley")
    assert burnley_fixture.is_home is False  # Palace home vs Burnley -> Burnley away
    assert any(e.gameweek == 1 and e.is_home is False for e in meta.exploiters)
