"""Routing-specific criteria for Jev's tool-selection choice question (v2).

v1 (in measure_jev_tool_routing.build_criteria) sends the first sentence of
each tool's tool_schema_registry description. That kept the discriminator
for tools whose authors front-loaded it and gutted the ones whose contrasts
("NOT for ...", "Use for '...'", axis definitions) come later -- which is
exactly where v1 missed (team_fixtures, advice).

v2 follows TypeSafe's Choice guidance for near-neighbour options: each
option is an object with `what` (the discriminator), `not_for` (the
neighbours it is confused with, by name) and `examples`. Distilled from the
full descriptions; orchestration imperatives ("call this tool TWICE",
"NEVER total prices yourself") are deliberately dropped -- Jev selects, it
does not execute.

The `examples` are paraphrases written for this file. None is a question
from tool_routing_corpus.CORPUS, so the corpus stays a held-out test set.
"""
from __future__ import annotations

NONE_OPTION = "none_of_these"

CRITERIA_V2: dict[str, dict[str, object]] = {
    # ----------------------------------------------------------------- team fixtures
    "get_fixture_outlook": {
        "what": "A difficulty VERDICT on upcoming fixtures along an axis: attack (how easy it is to score) or defence (how easy it is to keep a clean sheet). For one club, for one specific match of a club, or for ALL clubs ranked on that axis when the question names attack/defence.",
        "not_for": "A plain list of who a club plays next with no difficulty judgement (get_team_schedule); ranking every club by generic difficulty with no attack/defence axis (get_team_fixture_calendar); ranking by player position GKP/DEF/MID/FWD (get_position_fixture_run); the full round of matches for all clubs (get_fixtures_for_gw); one player's own run (get_player_fixture_run).",
        "examples": [
            "¿qué tan fácil viene el calendario del Arsenal en ataque las próximas 6 jornadas?",
            "para la portería, ¿cómo pinta el fixture del Liverpool?",
            "Tottenham vs Chelsea de local en la J4: ¿cómo se ve ofensivamente para el Tottenham?",
        ],
    },
    "get_team_schedule": {
        "what": "One club's next opponents: who, home or away, with double/blank gameweek labels. An opponent list, with no difficulty verdict.",
        "not_for": "How easy or hard that run is for scoring or clean sheets (get_fixture_outlook); comparing all clubs (get_team_fixture_calendar); form and top players of the club (get_team_snapshot).",
        "examples": [
            "¿a quién enfrenta el Brentford en las próximas 4 fechas?",
            "dame los rivales del Villa hasta la jornada 10",
        ],
    },
    "get_team_fixture_calendar": {
        "what": "Rank ALL Premier League clubs by upcoming generic fixture difficulty (FDR) over N gameweeks, easiest to hardest.",
        "not_for": "One named club (get_team_schedule or get_fixture_outlook); ranking on an attack or defence axis (get_fixture_outlook); ranking for one player position such as defenders (get_position_fixture_run); one player (get_player_fixture_run); the matches of a single round (get_fixtures_for_gw).",
        "examples": [
            "¿qué equipos tienen el calendario más fácil en las próximas 5 jornadas?",
            "ranking de fixtures difíciles para las próximas fechas",
        ],
    },
    "get_team_snapshot": {
        "what": "An overview of ONE club: recent form, its next fixtures with difficulty, and its top players with their stats.",
        "not_for": "Only the fixture list (get_team_schedule); only a fixture difficulty verdict (get_fixture_outlook); one player rather than a club (get_player_snapshot).",
        "examples": [
            "¿cómo viene el Bournemouth? forma, mejores jugadores y qué le toca",
            "resumen del Everton",
        ],
    },
    "get_fixtures_for_gw": {
        "what": "Every match of ONE gameweek for all 20 clubs: kickoff, both teams, difficulty, scores, plus which clubs have a double or blank that round.",
        "not_for": "One club's outlook or one specific match judged for a team (get_fixture_outlook); one club's list of upcoming opponents (get_team_schedule).",
        "examples": [
            "¿qué partidos hay en la jornada 6?",
            "mostrame todos los cruces de la próxima fecha",
        ],
    },
    # ----------------------------------------------------------------- player views
    "get_player_snapshot": {
        "what": "One named player's current profile and season-to-date stats: price, ownership, points, minutes, expected goals and assists, status.",
        "not_for": "Recent form over the last few games (get_player_form); a per-gameweek breakdown (get_player_history); the player's upcoming opponents (get_player_fixture_run); a past season's total (get_player_season_points); a captaincy verdict (get_captain_score).",
        "examples": [
            "contame de Isak",
            "¿cuánto cuesta y cuántos puntos lleva Palmer?",
            "¿está lesionado Rice?",
        ],
    },
    "get_player_form": {
        "what": "One player's RECENT form: minutes, goals, assists, bonus and points over the last few gameweeks.",
        "not_for": "A general profile or season totals (get_player_snapshot); a detailed per-gameweek table with expected stats (get_player_history); a past season (get_player_season_points).",
        "examples": [
            "¿cómo viene Saka en los últimos partidos?",
            "forma reciente de Watkins",
        ],
    },
    "get_player_history": {
        "what": "One player's gameweek-by-gameweek table for the last N rounds: minutes, points, goals, assists, xG, xA, BPS, with a summary.",
        "not_for": "A quick 'how is he doing lately' read (get_player_form); current profile (get_player_snapshot); a whole past season (get_player_season_points).",
        "examples": [
            "desglose jornada por jornada de Salah en las últimas 8",
            "historial de puntos de Haaland por fecha",
        ],
    },
    "get_player_fixture_run": {
        "what": "The upcoming opponents for ONE player: who his club faces, home or away, and difficulty per gameweek.",
        "not_for": "A club named directly rather than via a player (get_team_schedule / get_fixture_outlook); the player's stats (get_player_snapshot).",
        "examples": [
            "¿qué rivales le vienen a Mbeumo?",
            "fixture de Semenyo las próximas 5",
        ],
    },
    "get_player_season_points": {
        "what": "One player's TOTAL for a PAST or explicitly named season: points, goals, assists, clean sheets, bonus, minutes.",
        "not_for": "The current season's running total (get_player_snapshot); recent games (get_player_form / get_player_history); the top scorer of one gameweek (get_historical_gameweek_top_scorer).",
        "examples": [
            "¿cuántos puntos hizo Salah la temporada pasada?",
            "goles de Haaland en la 2023-24",
        ],
    },
    # ----------------------------------------------------------------- captaincy
    "get_captain_score": {
        "what": "A captaincy verdict for ONE named player for a gameweek: tier, confidence and the signals behind it.",
        "not_for": "Choosing between two named players (compare_players); an open list of the best captains (rank_captain_candidates); a general profile (get_player_snapshot); chip decisions like triple captain (get_chip_advice).",
        "examples": [
            "¿es buena idea capitanear a Palmer esta jornada?",
            "¿Isak de capitán?",
        ],
    },
    "compare_players": {
        "what": "A head-to-head between TWO named players on captain score, with a recommendation of which is better.",
        "not_for": "One player alone (get_captain_score); an open ranking with no named pair (rank_captain_candidates); a sell-one-buy-the-other transfer decision (get_transfer_advice).",
        "examples": [
            "¿Saka o Palmer de capitán?",
            "Haaland vs Isak, ¿quién es mejor esta semana?",
        ],
    },
    "rank_captain_candidates": {
        "what": "A ranked list of the best captain options for a gameweek, from the global pool or from named candidates, including the user's own squad when connected.",
        "not_for": "One named player (get_captain_score); exactly two named players (compare_players); low-ownership picks (get_differential_picks).",
        "examples": [
            "¿quiénes son los mejores capitanes para esta jornada?",
            "top 5 opciones de capitán",
            "de mi equipo, ¿a quién le pongo la cinta?",
        ],
    },
    # ----------------------------------------------------------------- squad building
    "build_squad": {
        "what": "Build a complete, legal 15-player squad under a budget: exact position quotas, max 3 per club, prices that add up. For a full team or wildcard draft.",
        "not_for": "A smaller number of players of one position that must fit a budget (select_players_within_budget); a ranked list with no budget arithmetic (rank_players_by_metric / get_transfer_suggestion); the chip verdict itself (get_chip_advice).",
        "examples": [
            "armame un equipo completo con 100 millones",
            "borrador de wildcard desde cero",
        ],
    },
    "select_players_within_budget": {
        "what": "Pick the best N players of ONE position that fit a budget while the rest of a legal squad stays completable. For a slice of the squad, not all 15.",
        "not_for": "A whole 15-player team (build_squad); a ranked list with no shared-budget arithmetic (get_transfer_suggestion / rank_players_by_metric).",
        "examples": [
            "¿qué 3 defensas puedo pagar si ya tengo a Haaland?",
            "dos delanteros que me alcancen con lo que me queda",
        ],
    },
    "get_transfer_suggestion": {
        "what": "Ranked transfer TARGETS to bring in, filtered by position, club or a per-player price ceiling, considering the upcoming run.",
        "not_for": "Deciding whether to sell one named player for another (get_transfer_advice); low-ownership picks specifically (get_differential_picks); a set of players that must fit one budget together (select_players_within_budget); a full squad (build_squad).",
        "examples": [
            "¿qué mediocampistas de menos de 7 millones conviene fichar?",
            "mejores delanteros para traer las próximas jornadas",
        ],
    },
    "rank_players_by_metric": {
        "what": "Top or bottom N players by ONE current-season metric: points, goals, assists, xG, price, ownership, transfers in/out, set-piece order, cards, saves, per-90 rates. Present state only, no fixtures.",
        "not_for": "Who to buy for the upcoming run (get_transfer_suggestion); a legal squad or budget arithmetic (build_squad / select_players_within_budget); one gameweek's top scorer from history (get_historical_gameweek_top_scorer).",
        "examples": [
            "¿quién tiene más goles esta temporada?",
            "los 10 más transferidos esta jornada",
            "defensas más baratos con más de 500 minutos",
        ],
    },
    # ----------------------------------------------------------------- advice
    "get_transfer_advice": {
        "what": "A sell-or-keep verdict for a specific swap: should I sell player X to bring in player Y.",
        "not_for": "Finding who to buy with no named outgoing player (get_transfer_suggestion); a captaincy head-to-head (compare_players); low-ownership picks (get_differential_picks).",
        "examples": [
            "¿vendo a Watkins por Isak?",
            "¿conviene sacar a Saka y meter a Palmer?",
        ],
    },
    "get_differential_picks": {
        "what": "Low-ownership picks (under 15% owned) ranked by score: differentials to gain ground on the field.",
        "not_for": "Popular or template transfer targets (get_transfer_suggestion); a named-player swap (get_transfer_advice); captaincy (rank_captain_candidates).",
        "examples": [
            "dame diferenciales para esta jornada",
            "jugadores poco seleccionados que puedan explotar",
        ],
    },
    "get_chip_advice": {
        "what": "Whether to play a CHIP this gameweek: triple captain, wildcard, bench boost or free hit, based on gameweek type (double/blank), fixtures and captain signals.",
        "not_for": "Just the gameweek number, deadline or double/blank alerts (get_gameweek_context / get_current_gameweek); building the squad the chip would use (build_squad); who to captain (rank_captain_candidates).",
        "examples": [
            "¿uso el triple capitán esta semana?",
            "¿es buena jornada para el bench boost?",
            "¿me conviene tirar el wildcard ya?",
        ],
    },
    # ----------------------------------------------------------------- gameweek state
    "get_current_gameweek": {
        "what": "Only the number of the current or next gameweek.",
        "not_for": "Deadline, double or blank alerts (get_gameweek_context); the matches of the round (get_fixtures_for_gw).",
        "examples": [
            "¿en qué jornada estamos?",
            "¿qué número de fecha es la próxima?",
        ],
    },
    "get_gameweek_context": {
        "what": "The current and next gameweek with their DEADLINES, season status, and which upcoming rounds are double or blank.",
        "not_for": "Only the gameweek number (get_current_gameweek); the match list (get_fixtures_for_gw); whether to play a chip on a double (get_chip_advice).",
        "examples": [
            "¿cuándo cierra el plazo de la próxima jornada?",
            "¿hay doble jornada pronto?",
        ],
    },
    "get_historical_gameweek_top_scorer": {
        "what": "Which PLAYER scored the most FPL POINTS in one finished gameweek ('jugador de la jornada'), or the table of every round's top scorer for a season.",
        "not_for": "Goals rather than FPL points (rank_players_by_metric); a player's season total (get_player_season_points); deadlines or fixtures (get_gameweek_context).",
        "examples": [
            "¿quién fue el jugador de la jornada 12?",
            "el que más puntos hizo en la fecha pasada",
        ],
    },
    # ----------------------------------------------------------------- full-catalog additions
    # Tools luna could pick but the corpus never labels. Added so Jev faces the
    # same menu (minus zonal, excluded by the corpus, and the four FI-7b1
    # non-operational shells, which are behind FOOTBALL_INTELLIGENCE_ENABLED
    # and off by default -- luna didn't have them either).
    "get_my_squad": {
        "what": "The connected user's OWN current 15-player squad: starting XI, bench, captain, prices, availability, active chip. For any question that presupposes the user already has a squad, with or without a possessive: 'mi equipo', 'mi plantilla', 'the rest of my team', 'the budget I have left', 'after these transfers', 'I need 4 midfielders'.",
        "not_for": "A general market question with no reference to an existing squad (rank_players_by_metric / get_transfer_suggestion); comparing two players (compare_players); the state of the gameweek (get_gameweek_context); a hypothetical or someone else's team.",
        "examples": [
            "evaluá mi plantilla para esta jornada",
            "con lo que me queda después de vender a Salah, ¿qué medio meto?",
            "¿quién está en mi banco?",
        ],
    },
    "get_injury_list": {
        "what": "The LIST of all currently injured, doubtful or unavailable players across the league, with status, chance of playing and news.",
        "not_for": "Whether ONE named player is fit (get_player_snapshot, which carries his availability); price changes (get_price_changes).",
        "examples": [
            "¿quiénes están lesionados esta semana?",
            "lista de dudas para la jornada",
        ],
    },
    "get_price_changes": {
        "what": "Players whose price just rose or fell: risers and fallers this gameweek.",
        "not_for": "One player's current price (get_player_snapshot); ranking players by price (rank_players_by_metric); who is injured (get_injury_list).",
        "examples": [
            "¿quién subió de precio anoche?",
            "bajadas de precio de esta semana",
        ],
    },
    "get_position_fixture_run": {
        "what": "Rank clubs by generic fixture difficulty (FDR) for ONE player position: best fixtures for defenders, midfielders, forwards or goalkeepers.",
        "not_for": "An attack-or-defence axis verdict (get_fixture_outlook); all clubs with no position (get_team_fixture_calendar); one club (get_team_schedule); one player (get_player_fixture_run).",
        "examples": [
            "¿qué equipos tienen mejores fixtures para mediocampistas las próximas 5?",
        ],
    },
    "find_players": {
        "what": "Fuzzy SEARCH for players by a partial, misspelled or ambiguous name, returning candidates.",
        "not_for": "A clearly named player's profile (get_player_snapshot); confirming one identity (resolve_player); ranking by a metric (rank_players_by_metric).",
        "examples": [
            "buscá jugadores que se llamen algo como 'Gvardiol'",
            "¿hay algún jugador apellidado Silva en el Chelsea?",
        ],
    },
    "resolve_player": {
        "what": "Resolve a name to ONE canonical player identity: full name, club, position. Identity only, no stats.",
        "not_for": "Stats or profile (get_player_snapshot); searching several candidates (find_players).",
        "examples": [
            "¿quién es 'Kudus', de qué equipo es?",
        ],
    },
    "get_player_summary": {
        "what": "A compact legacy summary of one player: position, price, ownership, availability.",
        "not_for": "The full current profile with points, minutes and expected stats (get_player_snapshot) -- prefer that for any general named-player question.",
        "examples": [
            "precio y porcentaje de propiedad de Rogers, nada más",
        ],
    },
    "web_fetch": {
        "what": "Fetch a news article or page from an allowlisted football site (BBC Sport, The Athletic, Premier League, FPL, FBref, Transfermarkt) when the user gives or clearly asks for a URL or latest press news.",
        "not_for": "Anything answerable from FPL data: stats, fixtures, prices, injuries, captaincy, squads.",
        "examples": [
            "traeme lo que dice esta nota de la BBC: https://www.bbc.com/sport/football/…",
            "¿qué dice la prensa hoy sobre la lesión de Ødegaard?",
        ],
    },
    # ----------------------------------------------------------------- no match
    NONE_OPTION: {
        "what": "The question is not answered by any tool above: off-topic, not about Fantasy Premier League, or asks for something none of these tools provide.",
        "examples": [
            "¿qué opinás del VAR?",
            "recomendame una serie",
        ],
    },
}


# ---------------------------------------------------------------------------
# Plans as route options (multi-tool compositions). Jev picks the plan; CODE
# executes its fixed tool sequence and gates each step. The wording of
# plan_chip_general_then_my_squad follows Card E (decided 2026-09-19): a chip
# question about an existing/unspecified squad is answered general (is this
# a good GW for the chip, which team group makes it so) THEN particular (does
# the user's squad hold that group), with or without a possessive. Build-
# from-scratch stays its own plan because part 2 there is build_squad.
# ---------------------------------------------------------------------------
PLANS_V2: dict[str, dict[str, object]] = {
    "plan_fixture_cell_both_axes_with_players": {
        "what": "ONE specific match of ONE club judged on BOTH attack and defence, naming that club's real players: fixture outlook on both axes plus the team snapshot, together.",
        "not_for": "A single axis (get_fixture_outlook alone); a club overview with no specific match (get_team_snapshot); a plain schedule (get_team_schedule).",
        "examples": ["Arsenal vs BHA (a domicilio), J5: ¿qué tal pinta ofensivamente y defensivamente para el Arsenal?"],
    },
    "plan_chip_general_then_my_squad": {
        "what": "Whether to PLAY a chip (bench boost, triple captain, wildcard, free hit) on the user's existing squad this or a named gameweek -- whether or not they mention their squad: first the general verdict for the gameweek, then how their own squad fits it.",
        "not_for": "Building a new squad from scratch and then judging a chip (plan_build_squad_then_chip); a chip's rules or window with no decision asked (get_chip_advice); a transfer decision with no chip (get_transfer_advice).",
        "examples": ["¿tiro el bench boost esta fecha?", "evalúa mi plantilla y decime si conviene el triple captain"],
    },
    "plan_build_squad_then_chip": {
        "what": "Build a squad FROM SCRATCH under a budget AND judge whether a chip (wildcard, free hit, bench boost) is viable on it.",
        "not_for": "A chip decision on an existing squad (plan_chip_general_then_my_squad); a build with no chip question (build_squad).",
        "examples": ["¿conviene el wildcard en la fecha 3 armando el equipo desde cero?"],
    },
}
