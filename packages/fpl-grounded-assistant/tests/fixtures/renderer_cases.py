"""Representative raw tool outputs for the renderers localised in i18n S5a.

Pure data (no package imports) so the same file can be loaded by the golden
generator against the pre-S5a renderer and by the test against the new one.
Each case is ``(name, tool_name, payload)``. Every branch of the converted
renderers is hit at least once.
"""
from __future__ import annotations


def _cand(rank, pid, name, team, score, owned=False, pos="MID", tier="safe"):
    return {
        "rank": rank, "player_id": pid, "web_name": name, "team_short": team, "position": pos,
        "captain_score": score, "tier": tier, "status": "ok", "owned": owned,
        "role_signals": {}, "score_inputs": {},
    }


_CANDS = [_cand(1, 10, "Saka", "ARS", 71.5, owned=True), _cand(2, 11, "Palmer", "CHE", 68.0),
          _cand(3, 12, "Haaland", "MCI", 66.5, pos="FWD")]

_SUMMARY = {"played": 5, "won": 3, "drawn": 1, "lost": 1, "gf": 9, "ga": 4,
            "clean_sheets": 2, "avg_gf": 1.8, "avg_ga": 0.8}

CASES: list[tuple[str, str, dict]] = [
    # -- rank_captain_candidates -------------------------------------------------
    ("captain_derived_not_connected", "rank_captain_candidates", {
        "status": "ok", "pool_source": "derived", "squad_source": "not_connected",
        "ranked_candidates": _CANDS, "presentation": {"global_top": [10, 11, 12], "global_hipster": {}},
        "time_context": {"evaluated_gameweek": 7, "gameweek_to": 7, "source": "current", "notice": "n"},
    }),
    ("captain_derived_connected_excluded", "rank_captain_candidates", {
        "status": "ok", "pool_source": "derived", "squad_source": "connected",
        "ranked_candidates": _CANDS,
        "presentation": {"owned_top": [10], "global_top": [10, 11, 12],
                         "owned_hipster": {"player_id": 11, "selected_by_percent": 4.25},
                         "global_hipster": {"player_id": 12}},
        "squad_excluded": [{"web_name": "Rice", "reason": "unavailable"}, {"web_name": "Odegaard", "reason": "unresolved"}],
        "time_context": {"evaluated_gameweek": 7, "gameweek_to": 9, "source": "requested", "notice": "n"},
    }),
    ("captain_derived_connected_no_owned", "rank_captain_candidates", {
        "status": "ok", "pool_source": "derived", "squad_source": "connected",
        "ranked_candidates": [_cand(1, 11, "Palmer", "CHE", 68.0), _cand(2, 12, "Haaland", "MCI", 66.5, pos="FWD")],
        "presentation": {"owned_top": [], "global_top": [11, 12], "owned_hipster": {}, "global_hipster": {"player_id": None}},
    }),
    ("captain_derived_unavailable", "rank_captain_candidates", {
        "status": "ok", "pool_source": "derived", "squad_source": "unavailable",
        "ranked_candidates": _CANDS, "presentation": {"global_top": [10, 11]},
    }),
    ("captain_caller_pool", "rank_captain_candidates", {
        "status": "ok", "pool_source": "caller", "ranked_candidates": _CANDS,
        "time_context": {"evaluated_gameweek": None, "source": "current", "notice": "n"},
    }),
    ("captain_none", "rank_captain_candidates", {"status": "ok", "ranked_candidates": []}),
    ("captain_error", "rank_captain_candidates", {"status": "error", "code": "bad"}),
    # -- get_team_results --------------------------------------------------------
    ("team_results_all", "get_team_results", {
        "status": "ok", "team": {"name": "Arsenal", "short_name": "ARS"}, "venue": "all",
        "matches": [
            {"gameweek": 5, "is_home": True, "opponent_short": "LIV", "goals_for": 2, "goals_against": 1, "result": "W"},
            {"gameweek": None, "is_home": False, "opponent_short": "CHE", "goals_for": 0, "goals_against": 0, "result": "D"},
        ],
        "summary": _SUMMARY, "venue_split": {"home": _SUMMARY, "away": _SUMMARY},
    }),
    ("team_results_home", "get_team_results", {
        "status": "ok", "team": {"name": "Arsenal"}, "venue": "home", "matches": [],
        "summary": _SUMMARY, "venue_split": {"home": _SUMMARY, "away": {}},
    }),
    ("team_results_away", "get_team_results", {
        "status": "ok", "team": {"short_name": "ARS"}, "venue": "away", "matches": [],
        "summary": {}, "venue_split": {},
    }),
    ("team_results_ambiguous", "get_team_results", {"status": "ambiguous", "query": "Man"}),
    ("team_results_not_found", "get_team_results", {"status": "not_found", "query": "Xyz"}),
    ("team_results_error", "get_team_results", {"status": "error", "code": "boom"}),
    ("team_results_ambiguous_msg", "get_team_results", {"status": "ambiguous", "message": "custom"}),
    # -- historical top scorer ---------------------------------------------------
    ("top_scorer_single", "get_historical_gameweek_top_scorer", {
        "status": "ok", "season": "2024-25", "gw": 12,
        "entries": [{"event_id": 12, "web_name": "Salah", "team_short": "LIV", "position": "MID", "points": 21, "highlight": "hat-trick"}],
    }),
    ("top_scorer_season", "get_historical_gameweek_top_scorer", {
        "status": "ok", "season": "2024-25", "gw": None,
        "entries": [
            {"event_id": 1, "web_name": "A", "team_short": "ARS", "position": "FWD", "points": 15},
            {"event_id": 2, "web_name": "B", "team_short": "CHE", "position": "MID", "points": None},
        ],
    }),
    ("top_scorer_none", "get_historical_gameweek_top_scorer", {"status": "ok", "season": "2024-25", "entries": []}),
    ("top_scorer_not_finished", "get_historical_gameweek_top_scorer", {
        "status": "error", "code": "gameweek_not_finished", "gw": 30, "season": "2025-26"}),
    ("top_scorer_not_found", "get_historical_gameweek_top_scorer", {"status": "not_found"}),
    ("top_scorer_invalid", "get_historical_gameweek_top_scorer", {"status": "invalid_argument"}),
    ("top_scorer_error", "get_historical_gameweek_top_scorer", {"status": "error", "code": "x"}),
    # -- find_players ------------------------------------------------------------
    ("find_players_ok", "find_players", {
        "status": "ok", "query": "sak",
        "matches": [{"web_name": "Saka", "team_short": "ARS", "position": "MID", "now_cost": 101, "form": 7.5,
                     "total_points": 80, "minutes_played_season": 900}],
    }),
    ("find_players_empty", "find_players", {"status": "ok", "query": "zzz", "matches": []}),
    ("find_players_not_found", "find_players", {"status": "not_found", "query": "zzz"}),
    ("find_players_error", "find_players", {"status": "error", "code": "e"}),
    # -- get_player_history ------------------------------------------------------
    ("history_ok", "get_player_history", {
        "status": "ok", "player": {"web_name": "Saka", "team_short": "ARS", "position": "MID"}, "last_n_gws": 2,
        "history": [
            {"round": 5, "opponent_team_short": "LIV", "minutes": 90, "total_points": 9, "goals_scored": 1,
             "assists": 0, "expected_goals": 0.55, "expected_assists": 0.1},
            {"round": 6, "opponent_team_short": "CHE", "minutes": 60, "total_points": 2, "goals_scored": 0,
             "assists": 0, "expected_goals": 0.1, "expected_assists": 0.0},
        ],
        "summary": {"total_points": 11, "avg_form": 5.5, "total_xgi": 0.75},
    }),
    ("history_empty", "get_player_history", {
        "status": "ok", "player": {"web_name": "Saka", "team_short": "ARS", "position": "MID"},
        "last_n_gws": 3, "history": [], "summary": {}}),
    ("history_ambiguous", "get_player_history", {"status": "ambiguous"}),
    ("history_not_found", "get_player_history", {"status": "not_found"}),
    ("history_error", "get_player_history", {"status": "error", "code": "e"}),
    # -- fixtures for gw ---------------------------------------------------------
    ("fixtures_gw_alerts", "get_fixtures_for_gw", {
        "status": "ok", "gw": 8, "is_blank": True, "is_double": True,
        "fixtures": [{"home_team_short": "ARS", "away_team_short": "CHE", "kickoff_time": "2026-10-18T14:00:00Z",
                      "home_fdr": 3, "away_fdr": 4}],
        "summary": {"double_gw_teams": ["ARS", "LIV"], "blank_gw_teams": ["MCI"]},
    }),
    ("fixtures_gw_none", "get_fixtures_for_gw", {"status": "ok", "gw": 9, "fixtures": [], "summary": {}}),
    ("fixtures_gw_invalid", "get_fixtures_for_gw", {"status": "invalid_argument"}),
    ("fixtures_gw_error", "get_fixtures_for_gw", {"status": "error", "code": "e"}),
    # -- gameweek context --------------------------------------------------------
    ("gw_context_ok", "get_gameweek_context", {
        "status": "ok", "current_gw": 8, "current_gw_status": "in progress", "next_gw": 9,
        "next_gw_deadline": "2026-10-25T10:00:00Z",
        "blank_gw_alerts": [{"gw": 10, "blank_teams": ["ARS", "LIV"]}],
        "double_gw_alerts": [{"gw": 11, "double_teams": ["CHE"]}],
    }),
    ("gw_context_no_next", "get_gameweek_context", {"status": "ok", "current_gw": 38, "current_gw_status": "finished"}),
    ("gw_context_over", "get_gameweek_context", {"status": "ok", "is_season_over": True}),
    ("gw_context_error", "get_gameweek_context", {"status": "error", "code": "e"}),
    # -- team snapshot -----------------------------------------------------------
    ("team_snapshot_easy", "get_team_snapshot", {
        "status": "ok", "team": {"short_name": "ARS", "name": "Arsenal"},
        "upcoming_fixtures": [{"gw": 8, "opponent_short": "BOU", "is_home": True, "fdr": 2},
                              {"gw": 9, "opponent_short": "LIV", "is_home": False, "fdr": 5}],
        "top_players": [{"web_name": "Saka", "position": "MID", "total_points": 80, "form": 7.5, "now_cost": 101}],
        "summary": {"avg_fdr_next_5": 2.8, "is_easy_run": True, "top_scorer_web_name": "Saka", "top_form_web_name": "Saka"},
    }),
    ("team_snapshot_hard", "get_team_snapshot", {
        "status": "ok", "team": {"short_name": "ARS", "name": "Arsenal"},
        "summary": {"avg_fdr_next_5": 4.2, "is_hard_run": True}}),
    ("team_snapshot_mid", "get_team_snapshot", {
        "status": "ok", "team": {"short_name": "ARS", "name": "Arsenal"}, "summary": {"avg_fdr_next_5": 3.0}}),
    ("team_snapshot_ambiguous", "get_team_snapshot", {
        "status": "ambiguous", "query": "man", "candidates": [{"short_name": "MCI"}, {"short_name": "MUN"}]}),
    ("team_snapshot_not_found", "get_team_snapshot", {"status": "not_found"}),
    ("team_snapshot_error", "get_team_snapshot", {"status": "error", "code": "e"}),
    # -- web ---------------------------------------------------------------------
    ("search_web_ok", "search_web", {
        "status": "ok", "results": [{"title": "T", "snippet": "S", "source": "bbc.co.uk"}]}),
    ("search_web_none", "search_web", {"status": "ok", "results": []}),
    ("search_web_error", "search_web", {"status": "error", "code": "e"}),
    ("web_fetch_ok", "web_fetch", {
        "status": "ok", "url": "https://x.test", "content_length": 120, "text_excerpt": "hello", "truncated": True}),
    ("web_fetch_ok_full", "web_fetch", {
        "status": "ok", "url": "https://x.test", "content_length": 5, "text_excerpt": "hello"}),
    ("web_fetch_refused", "web_fetch", {"status": "refused"}),
    ("web_fetch_error", "web_fetch", {"status": "error", "code": "e", "http_status": 503}),
    # -- rank_players_by_metric --------------------------------------------------
    ("metric_ok", "rank_players_by_metric", {
        "status": "ok", "metric": "form", "position_filter": "MID", "min_minutes_filter": 300, "order": "desc",
        "ranked": [{"rank": 1, "web_name": "Saka", "team_short": "ARS", "position": "MID", "metric_value": 7.5}]}),
    ("metric_inverted_asc", "rank_players_by_metric", {
        "status": "ok", "metric": "now_cost", "min_minutes_filter": 0, "order": "asc",
        "ranked": [{"rank": 1, "web_name": "Cheap", "team_short": "BUR", "position": "DEF", "metric_value": 3.9}]}),
    ("metric_inverted_desc", "rank_players_by_metric", {
        "status": "ok", "metric": "minutes", "min_minutes_filter": 0, "order": "desc",
        "ranked": [{"rank": 1, "web_name": "X", "team_short": "BUR", "position": "DEF", "metric_value": 3.9}]}),
    ("metric_none", "rank_players_by_metric", {
        "status": "ok", "metric": "form", "position_filter": "GKP", "min_minutes_filter": 0, "ranked": []}),
    ("metric_unknown", "rank_players_by_metric", {"status": "invalid_argument"}),
    ("metric_error", "rank_players_by_metric", {"status": "error", "code": "e"}),
    # -- build_squad -------------------------------------------------------------
    ("squad_ok", "build_squad", {
        "status": "ok", "squad_size": 15, "objective": "total_points", "ranking_basis": "season",
        "formation": "3-4-3",
        "squad": [{"position": "GKP", "web_name": "Raya", "team_short": "ARS", "price": 5.5, "objective_value": 100, "id": 1},
                  {"position": "MID", "web_name": "Saka", "team_short": "ARS", "price": 10.1, "objective_value": 120, "id": 2, "locked": True}],
        "starting_xi": [{"id": 1}], "total_cost": 100.0, "budget": 100.0, "remaining": 0.0,
        "club_counts": {"ARS": 2, "CHE": 1}, "warnings": ["w1"]}),
    ("squad_ok_minimal", "build_squad", {"status": "ok", "squad": [], "starting_xi": []}),
    ("squad_infeasible", "build_squad", {"status": "infeasible"}),
    ("squad_ambiguous", "build_squad", {"status": "ambiguous", "candidates": [{"web_name": "A"}, {"web_name": "B"}]}),
    ("squad_ambiguous_none", "build_squad", {"status": "ambiguous", "candidates": []}),
    ("squad_not_found", "build_squad", {"status": "not_found"}),
    ("squad_invalid", "build_squad", {"status": "invalid_argument"}),
    ("squad_error", "build_squad", {"status": "error", "code": "e"}),
]
