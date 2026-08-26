"""Labelled Spanish-language corpus for the tool-routing confusion measurement.

Each entry is a real-ish user question (Spanish-first, Spanglish where the
product's users actually write that way) labelled with an ACCEPTABLE SET of
tool names, not a single expected tool. Many questions genuinely admit more
than one correct first tool call; a single-answer key would manufacture
failures that are really a labelling mistake. Where a defensible single-tool
answer exists, ``control`` is True and ``acceptable_tools`` has one entry --
these exist to distinguish "boundary confusion" from "something worse".

Families match the ones named in the measurement task. ``chip_vs_gameweek``
is a dedicated bucket around the known failing case (get_gameweek_context
picked over get_chip_advice), including the pinned verbatim question.

Zonal tools (get_player_zonal_outlook, get_zonal_opportunity,
get_zonal_weakness) are deliberately absent from every acceptable set: they
return missing_context in a worktree because packages/fpl-tactical/data/ is
gitignored -- an environment artifact, not something this corpus should
route towards. If the model picks one anyway it will show up as a routing
"miss" against a different expected family and must be excluded with that
reason stated, per the measurement task.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# team_fixtures -- get_team_snapshot / get_team_schedule /
#                  get_team_fixture_calendar / get_fixture_outlook
# ---------------------------------------------------------------------------
_TEAM_FIXTURES: list[dict[str, Any]] = [
    {
        "id": "tf-01", "family": "team_fixtures", "control": True,
        "question": "Dame un resumen completo del Liverpool: forma, top jugadores y sus próximos partidos.",
        "acceptable_tools": ["get_team_snapshot"],
        "note": "Multi-facet team overview (form + top players + fixtures) is only get_team_snapshot's shape.",
    },
    {
        "id": "tf-02", "family": "team_fixtures", "control": True,
        "question": "¿Qué equipos de la Premier tienen las fixtures más fáciles en las próximas 5 fechas?",
        "acceptable_tools": ["get_team_fixture_calendar"],
        "note": "Ranks ALL teams -- schema explicitly says NOT for single-team (get_team_schedule).",
    },
    {
        "id": "tf-03", "family": "team_fixtures", "control": True,
        "question": "¿Contra quién juega el Newcastle en las próximas 3 fechas?",
        "acceptable_tools": ["get_team_schedule"],
        "note": "Plain single-team opponent list, no difficulty verdict requested.",
    },
    {
        "id": "tf-04", "family": "team_fixtures", "control": True,
        "question": "Para efectos de capitanía, ¿qué tan fácil es el fixture del Manchester City en ataque en las próximas 6 fechas?",
        "acceptable_tools": ["get_fixture_outlook"],
        "note": "Explicit axis=attack framing + captaincy use-case is get_fixture_outlook's stated purpose.",
    },
    {
        "id": "tf-05", "family": "team_fixtures", "control": False,
        "question": "¿Cómo le está yendo al Brighton últimas fechas y qué fixtures le vienen?",
        "acceptable_tools": ["get_team_snapshot", "get_team_schedule"],
        "note": "Form+fixtures both asked; snapshot bundles both, schedule covers only the fixtures half.",
    },
    {
        "id": "tf-06", "family": "team_fixtures", "control": False,
        "question": "¿Qué tan complicadas son las próximas fechas del Everton?",
        "acceptable_tools": ["get_team_schedule", "get_fixture_outlook"],
        "note": "Difficulty framing without naming an axis -- both a plain schedule and the outlook tool are defensible.",
    },
    {
        "id": "tf-07", "family": "team_fixtures", "control": False,
        "question": "Dame las fixtures del Chelsea y decime si conviene para la defensa.",
        "acceptable_tools": ["get_team_schedule", "get_fixture_outlook"],
        "note": "Names a team + defensive framing; outlook(axis=defence) or a plain schedule read both defensible.",
    },
    {
        "id": "tf-08", "family": "team_fixtures", "control": False,
        "question": "¿Cuáles son los equipos con el fixture más jodido para la defensa en las próximas 5 fechas?",
        "acceptable_tools": ["get_team_fixture_calendar", "get_fixture_outlook"],
        "note": "All-teams ranking, defence-flavoured -- generic FDR ranker or axis=defence outlook both correct.",
    },
    {
        "id": "tf-09", "family": "team_fixtures", "control": False,
        "question": "Necesito saber qué equipos tienen un fixture run bueno para atacar en las próximas fechas.",
        "acceptable_tools": ["get_fixture_outlook", "get_team_fixture_calendar"],
        "note": "\"Run\" language matches get_fixture_outlook's run-detection, but the all-teams ranker also answers it.",
    },
    {
        "id": "tf-10", "family": "team_fixtures", "control": False,
        "question": "Dame un panorama del Aston Villa: cómo viene jugando y contra quién le toca.",
        "acceptable_tools": ["get_team_snapshot", "get_team_schedule"],
        "note": "\"Panorama\" (form) + \"contra quién\" (schedule) -- snapshot bundles both, schedule covers half.",
    },
    {
        "id": "tf-11", "family": "team_fixtures", "control": False,
        "question": "¿El Bournemouth tiene un fixture run positivo para los próximos partidos o mejor evito a sus jugadores?",
        "acceptable_tools": ["get_fixture_outlook", "get_team_schedule"],
        "note": "Ambiguous whether a difficulty verdict (outlook) or a plain schedule read is wanted.",
    },
    {
        "id": "tf-12", "family": "team_fixtures", "control": True,
        "question": "¿Cuál es el equipo con el fixture más fácil en defensa para las próximas 8 fechas?",
        "acceptable_tools": ["get_fixture_outlook"],
        "note": "All-teams + explicit axis (defence) + explicit horizon is get_fixture_outlook's exact shape.",
    },
    {
        "id": "tf-13", "family": "team_fixtures", "control": False,
        "question": "Antes de decidir si fichar un defensor del Wolves, ¿me tirás su calendario y qué tan duro está?",
        "acceptable_tools": ["get_team_schedule", "get_fixture_outlook"],
        "note": "\"Calendario\" (schedule) + \"qué tan duro\" (difficulty) overlap the two team-fixture tools.",
    },
    {
        "id": "tf-14", "family": "team_fixtures", "control": False,
        "question": "¿Los fixtures del Fulham están buenos o feos para las próximas 5 fechas?",
        "acceptable_tools": ["get_team_schedule", "get_fixture_outlook"],
        "note": "Spanglish \"fixtures ... buenos o feos\" is a bare good/bad verdict -- either tool defensibly answers it.",
    },
]

# ---------------------------------------------------------------------------
# player_views -- get_player_snapshot / get_player_fixture_run /
#                 get_player_form / get_player_history
# (compare_players lives primarily under captaincy; it is a player-vs-player
#  tool but its schema explicitly targets captain framing.)
# ---------------------------------------------------------------------------
_PLAYER_VIEWS: list[dict[str, Any]] = [
    {
        "id": "pv-01", "family": "player_views", "control": True,
        "question": "¿Cuánto cuesta Haaland y cuál es su ownership actual?",
        "acceptable_tools": ["get_player_snapshot"],
        "note": "Price + ownership is the player-profile payload; no other tool returns ownership.",
    },
    {
        "id": "pv-02", "family": "player_views", "control": True,
        "question": "¿Cómo viene de forma Saka en las últimas 5 fechas?",
        "acceptable_tools": ["get_player_form"],
        "note": "Explicit recent-form / last-games framing matches get_player_form's stated use.",
    },
    {
        "id": "pv-03", "family": "player_views", "control": True,
        "question": "¿Me pasás las últimas 10 fechas de Haaland con su xG y xA por partido?",
        "acceptable_tools": ["get_player_history"],
        "note": "Per-GW xG/xA breakdown is get_player_history's distinguishing field; get_player_form omits xG/xA.",
    },
    {
        "id": "pv-04", "family": "player_views", "control": True,
        "question": "¿Contra quién juega Palmer en las próximas 5 fechas y qué tan difícil es cada partido?",
        "acceptable_tools": ["get_player_fixture_run"],
        "note": "Single-player upcoming opponent+FDR run is get_player_fixture_run's exact shape.",
    },
    {
        "id": "pv-05", "family": "player_views", "control": False,
        "question": "¿Cómo viene Bukayo Saka esta temporada?",
        "acceptable_tools": ["get_player_snapshot", "get_player_form"],
        "note": "Vague \"cómo viene\" could mean season profile or recent-form -- both defensible.",
    },
    {
        "id": "pv-06", "family": "player_views", "control": False,
        "question": "¿Cómo le fue a Palmer en sus últimos partidos?",
        "acceptable_tools": ["get_player_form", "get_player_history"],
        "note": "Both tools cover recent-games detail; form is coarser, history is per-GW -- genuinely overlapping.",
    },
    {
        "id": "pv-07", "family": "player_views", "control": False,
        "question": "¿Qué número de goles y asistencias lleva Isak en toda la temporada hasta ahora?",
        "acceptable_tools": ["get_player_snapshot", "get_player_history"],
        "note": "Season totals could come from the profile directly or be summed from a long history window.",
    },
    {
        "id": "pv-08", "family": "player_views", "control": False,
        "question": "¿Vale la pena fichar a Mbeumo? Contame cómo viene y qué fixtures tiene.",
        "acceptable_tools": ["get_player_snapshot", "get_player_fixture_run"],
        "note": "Asks for both profile and fixture run in one question; either is a defensible first call.",
    },
    {
        "id": "pv-09", "family": "player_views", "control": False,
        "question": "Necesito saber si Enzo Fernández está en racha o viene flojo.",
        "acceptable_tools": ["get_player_form", "get_player_history"],
        "note": "\"Racha\" (streak/form) is ambiguous between the form summary and a raw per-GW history read.",
    },
    {
        "id": "pv-10", "family": "player_views", "control": True,
        "question": "¿Está disponible Rodri para jugar o sigue lesionado?",
        "acceptable_tools": ["get_player_snapshot"],
        "note": "Availability status lives on the player profile payload only.",
    },
    {
        "id": "pv-11", "family": "player_views", "control": True,
        "question": "Dame el detalle fecha por fecha de Gordon en lo que va de temporada.",
        "acceptable_tools": ["get_player_history"],
        "note": "\"Fecha por fecha\" (per-GW) is get_player_history's defining feature.",
    },
    {
        "id": "pv-12", "family": "player_views", "control": False,
        "question": "¿Qué tal viene jugando Gabriel Jesus y cómo tiene el fixture las próximas semanas?",
        "acceptable_tools": ["get_player_snapshot", "get_player_form", "get_player_fixture_run"],
        "note": "Compound question (form + fixtures); any of the three player views is a defensible starting tool.",
    },
    {
        "id": "pv-13", "family": "player_views", "control": True,
        "question": "¿Cuál es la posición y el precio de Declan Rice?",
        "acceptable_tools": ["get_player_snapshot"],
        "note": "Position + price is squarely the profile payload.",
    },
    {
        "id": "pv-14", "family": "player_views", "control": False,
        "question": "¿Bruno Fernandes viene de buena racha de goles y asistencias en las últimas fechas?",
        "acceptable_tools": ["get_player_form", "get_player_history"],
        "note": "Same recent-form-vs-history overlap as pv-06/pv-09, different player, checks consistency.",
    },
]

# ---------------------------------------------------------------------------
# captaincy -- get_captain_score / rank_captain_candidates / compare_players
# ---------------------------------------------------------------------------
_CAPTAINCY: list[dict[str, Any]] = [
    {
        "id": "cp-01", "family": "captaincy", "control": True,
        "question": "¿Qué tan buena opción de captain es Haaland esta fecha?",
        "acceptable_tools": ["get_captain_score"],
        "note": "Single named player scored alone -- get_captain_score's exact shape.",
    },
    {
        "id": "cp-02", "family": "captaincy", "control": True,
        "question": "¿A quién le pongo la cinta esta fecha, Salah o Haaland?",
        "acceptable_tools": ["compare_players"],
        "note": "Exactly two named players in a captain 'X or Y' frame is compare_players' stated use-case.",
    },
    {
        "id": "cp-03", "family": "captaincy", "control": True,
        "question": "Tengo estas 4 opciones de capitán: Haaland, Salah, Palmer y Isak. ¿Cómo las rankean de mejor a peor?",
        "acceptable_tools": ["rank_captain_candidates"],
        "note": "Four named candidates to be ranked is beyond compare_players' two-player limit.",
    },
    {
        "id": "cp-04", "family": "captaincy", "control": False,
        "question": "Entre Haaland y Watkins, ¿quién es mejor capitán esta fecha?",
        "acceptable_tools": ["compare_players", "rank_captain_candidates"],
        "note": "Exactly 2 named players -- the dedicated 2-player tool or the general ranker both correctly answer it.",
    },
    {
        "id": "cp-05", "family": "captaincy", "control": True,
        "question": "De estos tres, ¿cuál pongo de capitán: Haaland, Isak, Watkins?",
        "acceptable_tools": ["rank_captain_candidates"],
        "note": "Three named candidates exceed compare_players' two-player scope.",
    },
    {
        "id": "cp-06", "family": "captaincy", "control": False,
        "question": "¿Vale la pena poner de capitán a Palmer esta semana o mejor otro?",
        "acceptable_tools": ["get_captain_score", "rank_captain_candidates"],
        "note": "Names one player but leaves 'or someone else' open -- scoring Palmer alone or ranking alternatives both defensible.",
    },
    {
        "id": "cp-07", "family": "captaincy", "control": False,
        "question": "¿Isak o Watkins para la banda de capitán esta fecha, o hay alguien mejor que los dos?",
        "acceptable_tools": ["compare_players", "rank_captain_candidates"],
        "note": "Names two but explicitly invites a third option -- both the pairwise and ranking tools are defensible.",
    },
    {
        "id": "cp-08", "family": "captaincy", "control": True,
        "question": "¿Cómo puntúa Son como capitán esta fecha según forma y fixture?",
        "acceptable_tools": ["get_captain_score"],
        "note": "Single named player, explicit scoring language.",
    },
    {
        "id": "cp-09", "family": "captaincy", "control": False,
        "question": "¿Le doy la cinta a Haaland de nuevo o pruebo con Salah esta vez?",
        "acceptable_tools": ["compare_players", "rank_captain_candidates"],
        "note": "Same two-name captain framing as cp-04/cp-07, different phrasing register.",
    },
    {
        "id": "cp-10", "family": "captaincy", "control": True,
        "question": "Ordename estas opciones de capitán de mejor a peor: Haaland, Isak, Solanke, Watkins.",
        "acceptable_tools": ["rank_captain_candidates"],
        "note": "Explicit ordering request over 4 named players.",
    },
    {
        "id": "cp-11", "family": "captaincy", "control": False,
        "question": "¿Palmer es un lock para la cinta esta fecha o hay alguien que lo supere?",
        "acceptable_tools": ["get_captain_score", "rank_captain_candidates"],
        "note": "Same open-ended single-name-plus-alternatives ambiguity as cp-06.",
    },
    {
        "id": "cp-12", "family": "captaincy", "control": True,
        "question": "¿Qué tan seguro es capitanear a Rashford esta semana?",
        "acceptable_tools": ["get_captain_score"],
        "note": "Single named player captain-safety question.",
    },
]

# ---------------------------------------------------------------------------
# squad_building -- build_squad / select_players_within_budget /
#                   get_transfer_suggestion / rank_players_by_metric
# ---------------------------------------------------------------------------
_SQUAD_BUILDING: list[dict[str, Any]] = [
    {
        "id": "sb-01", "family": "squad_building", "control": True,
        "question": "Armá un equipo completo de wildcard con 100 millones.",
        "acceptable_tools": ["build_squad"],
        "note": "Full 15-man squad request -- build_squad's exact scope.",
    },
    {
        "id": "sb-02", "family": "squad_building", "control": True,
        "question": "Necesito 4 medios que me permita el presupuesto, ya tengo el resto del equipo armado.",
        "acceptable_tools": ["select_players_within_budget"],
        "note": "Explicit N-slice that must fit a combined budget -- select_players_within_budget's stated use.",
    },
    {
        "id": "sb-03", "family": "squad_building", "control": True,
        "question": "¿Cuáles son los mejores delanteros baratos para reforzar, sin importar el presupuesto exacto?",
        "acceptable_tools": ["get_transfer_suggestion"],
        "note": "Independent ranked suggestions, explicitly not a combined-budget proof -- get_transfer_suggestion.",
    },
    {
        "id": "sb-04", "family": "squad_building", "control": True,
        "question": "¿Quién lleva más goles esperados (xG) esta temporada entre todos los jugadores?",
        "acceptable_tools": ["rank_players_by_metric"],
        "note": "Present-state metric ranking with no fixture/budget angle -- rank_players_by_metric's exact scope.",
    },
    {
        "id": "sb-05", "family": "squad_building", "control": True,
        "question": "Con 15 millones y necesitando dos delanteros, ¿cuáles me recomendás que entren juntos?",
        "acceptable_tools": ["select_players_within_budget"],
        "note": "Explicit N (2) + combined budget that must fit together -- select_players_within_budget.",
    },
    {
        "id": "sb-06", "family": "squad_building", "control": False,
        "question": "¿Cuáles son los 3 mejores defensas baratos, sin pensar en presupuesto combinado?",
        "acceptable_tools": ["get_transfer_suggestion", "rank_players_by_metric"],
        "note": "\"Baratos\" (price-ranked) vs a scouting suggestion list -- both defensible, budget combination explicitly waived.",
    },
    {
        "id": "sb-07", "family": "squad_building", "control": False,
        "question": "¿Es viable el bench boost si armo un equipo desde cero para la fecha 1?",
        "acceptable_tools": ["build_squad", "get_chip_advice"],
        "note": "Schema for build_squad explicitly names this exact phrasing, then hands off to get_chip_advice for the chip verdict -- both are correct first moves.",
    },
    {
        "id": "sb-08", "family": "squad_building", "control": False,
        "question": "Quiero el mejor mediocampista de precio medio en base a puntos totales, sin importar el fixture.",
        "acceptable_tools": ["rank_players_by_metric", "get_transfer_suggestion"],
        "note": "Metric ranking (points) with a position+price filter overlaps both tools' scope.",
    },
    {
        "id": "sb-09", "family": "squad_building", "control": True,
        "question": "Haaland es un lock, así que arranco con -15.5 de mi presupuesto de 100. Armame el resto del equipo.",
        "acceptable_tools": ["build_squad"],
        "note": "Full 15-man squad with a locked player -- build_squad handles locked_players + budget directly.",
    },
    {
        "id": "sb-10", "family": "squad_building", "control": False,
        "question": "Decime tres defensas entre 4.5 y 6.0 millones que valgan la pena para las próximas fechas.",
        "acceptable_tools": ["get_transfer_suggestion", "rank_players_by_metric"],
        "note": "Position+price-ranged suggestion overlaps a metric ranking (points/price) and a scouting suggestion list.",
    },
    {
        "id": "sb-11", "family": "squad_building", "control": True,
        "question": "Necesito armar mi equipo ideal de arranque de temporada gastando el presupuesto completo de 100 millones.",
        "acceptable_tools": ["build_squad"],
        "note": "Full-15 squad-from-scratch request, same shape as sb-01/sb-09 with different phrasing.",
    },
    {
        "id": "sb-12", "family": "squad_building", "control": True,
        "question": "¿Quién tiene el mejor ratio de goles por 90 minutos esta temporada?",
        "acceptable_tools": ["rank_players_by_metric"],
        "note": "Per-90 present-state metric -- rank_players_by_metric's scope, control-strength but kept non-control since 'ratio' phrasing sometimes reads as a suggestion request.",
    },
    {
        "id": "sb-13", "family": "squad_building", "control": True,
        "question": "Necesito dos delanteros y un defensa que me entren en el presupuesto que me queda después de estas ventas.",
        "acceptable_tools": ["select_players_within_budget"],
        "note": "Explicit multi-position N-slice within a remaining budget -- select_players_within_budget, kept non-control since cross-position slicing is a slightly novel phrasing for the tool.",
    },
    {
        "id": "sb-14", "family": "squad_building", "control": False,
        "question": "¿Me armás un wildcard completo pero justificando cada fichaje por su fixture de las próximas 5 fechas?",
        "acceptable_tools": ["build_squad", "get_fixture_outlook"],
        "note": "Full-squad request (build_squad, fixture-blind per its own schema) plus an explicit fixture-justification ask that build_squad cannot satisfy alone.",
    },
]

# ---------------------------------------------------------------------------
# advice -- get_chip_advice / get_transfer_advice / get_differential_picks
# ---------------------------------------------------------------------------
_ADVICE: list[dict[str, Any]] = [
    {
        "id": "ad-01", "family": "advice", "control": True,
        "question": "¿Me conviene vender a Mitoma para comprar a Palmer?",
        "acceptable_tools": ["get_transfer_advice"],
        "note": "Explicit named sell/buy pair -- get_transfer_advice's exact shape.",
    },
    {
        "id": "ad-02", "family": "advice", "control": True,
        "question": "Dame opciones diferenciales de bajo ownership para esta fecha.",
        "acceptable_tools": ["get_differential_picks"],
        "note": "Explicit 'differential' / low-ownership request.",
    },
    {
        "id": "ad-03", "family": "advice", "control": True,
        "question": "¿Conviene usar el wildcard esta fecha?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Chip named explicitly, no squad-building or specific-GW-number framing.",
    },
    {
        "id": "ad-04", "family": "advice", "control": False,
        "question": "¿Debería tirar el triple captain este fin de semana con Haaland de local?",
        "acceptable_tools": ["get_chip_advice", "get_captain_score"],
        "note": "Chip question anchored to one named player -- chip advice or a captain-score check on Haaland both defensible.",
    },
    {
        "id": "ad-05", "family": "advice", "control": False,
        "question": "¿Me conviene hacer un transfer esta semana o mejor guardo el chip?",
        "acceptable_tools": ["get_transfer_advice", "get_chip_advice"],
        "note": "Mentions both a generic transfer and 'the chip' without naming either -- genuinely underspecified between the two advice tools.",
    },
    {
        "id": "ad-06", "family": "advice", "control": False,
        "question": "Tengo a Mitoma que no rinde, ¿lo cambio por alguien diferencial de bajo ownership?",
        "acceptable_tools": ["get_transfer_advice", "get_differential_picks"],
        "note": "Names the player to sell but the replacement is described only as 'differential' -- either advice tool is defensible.",
    },
    {
        "id": "ad-07", "family": "advice", "control": True,
        "question": "¿Es buen momento para usar el free hit?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Chip named explicitly, no GW-number or squad-building framing (contrast with the chip_vs_gameweek bucket).",
    },
    {
        "id": "ad-08", "family": "advice", "control": True,
        "question": "¿Qué jugadores de bajo ownership me recomendás para diferenciar de la media?",
        "acceptable_tools": ["get_differential_picks"],
        "note": "Same differential framing as ad-02 with different phrasing.",
    },
    {
        "id": "ad-09", "family": "advice", "control": False,
        "question": "¿Saco a Rodri y meto a alguien más barato y diferencial?",
        "acceptable_tools": ["get_transfer_advice", "get_differential_picks"],
        "note": "Same named-sell + vague-differential-buy ambiguity as ad-06.",
    },
    {
        "id": "ad-10", "family": "advice", "control": True,
        "question": "¿Debería activar el bench boost esta ronda?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Chip named explicitly, relative 'esta ronda' with no specific GW number attached.",
    },
    {
        "id": "ad-11", "family": "advice", "control": False,
        "question": "¿Palmer por Saka es un buen cambio, o mejor uso ese transfer para meter un diferencial?",
        "acceptable_tools": ["get_transfer_advice", "get_differential_picks"],
        "note": "Named swap explicitly framed as an alternative to a differential pick -- both advice tools defensible.",
    },
    {
        "id": "ad-12", "family": "advice", "control": True,
        "question": "¿Me conviene cambiar a Sterling por Gordon esta semana?",
        "acceptable_tools": ["get_transfer_advice"],
        "note": "Named sell/buy pair, same shape as ad-01.",
    },
]

# ---------------------------------------------------------------------------
# gameweek_state -- get_current_gameweek / get_gameweek_context /
#                   get_fixtures_for_gw
# ---------------------------------------------------------------------------
_GAMEWEEK_STATE: list[dict[str, Any]] = [
    {
        "id": "gw-01", "family": "gameweek_state", "control": True,
        "question": "¿En qué gameweek estamos ahora?",
        "acceptable_tools": ["get_current_gameweek"],
        "note": "Bare GW number only, nothing else asked.",
    },
    {
        "id": "gw-02", "family": "gameweek_state", "control": True,
        "question": "Dame todos los partidos de la fecha 5 con su dificultad.",
        "acceptable_tools": ["get_fixtures_for_gw"],
        "note": "Explicit GW number + full fixture list -- get_fixtures_for_gw's exact shape.",
    },
    {
        "id": "gw-03", "family": "gameweek_state", "control": True,
        "question": "¿Hay double gameweek o blank gameweek en las próximas fechas?",
        "acceptable_tools": ["get_gameweek_context"],
        "note": "Explicit blank/double alert question -- only get_gameweek_context returns those.",
    },
    {
        "id": "gw-04", "family": "gameweek_state", "control": True,
        "question": "¿Qué fecha es la próxima y cuándo cierra el mercado de fichajes?",
        "acceptable_tools": ["get_gameweek_context"],
        "note": "Deadline is explicitly asked; get_current_gameweek's payload has no deadline field.",
    },
    {
        "id": "gw-05", "family": "gameweek_state", "control": False,
        "question": "¿Qué gameweek es la actual?",
        "acceptable_tools": ["get_current_gameweek", "get_gameweek_context"],
        "note": "Bare current-GW question with no deadline/alert ask -- the richer context tool over-answers it but isn't wrong.",
    },
    {
        "id": "gw-06", "family": "gameweek_state", "control": False,
        "question": "Dame el calendario de partidos de la fecha que viene.",
        "acceptable_tools": ["get_gameweek_context", "get_fixtures_for_gw"],
        "note": "\"La fecha que viene\" needs resolving to a number first (context) or the model may guess the number directly (fixtures_for_gw).",
    },
    {
        "id": "gw-07", "family": "gameweek_state", "control": True,
        "question": "¿A qué hora juega cada equipo en la fecha 8?",
        "acceptable_tools": ["get_fixtures_for_gw"],
        "note": "Explicit GW number + kickoff-level detail, same shape as gw-02.",
    },
    {
        "id": "gw-08", "family": "gameweek_state", "control": False,
        "question": "¿Estamos por entrar en una fecha con blank gameweek? Si es así, decime qué partidos hay esa fecha.",
        "acceptable_tools": ["get_gameweek_context", "get_fixtures_for_gw"],
        "note": "Two-part question; resolving the alert first (context) or guessing the fixture list directly are both plausible first moves.",
    },
    {
        "id": "gw-09", "family": "gameweek_state", "control": True,
        "question": "Nada más decime el número de la gameweek actual, sin nada más.",
        "acceptable_tools": ["get_current_gameweek"],
        "note": "Explicitly asks for nothing but the bare number.",
    },
    {
        "id": "gw-10", "family": "gameweek_state", "control": False,
        "question": "¿Falta mucho para que cierre el plazo de la próxima fecha?",
        "acceptable_tools": ["get_gameweek_context", "get_current_gameweek"],
        "note": "Deadline-flavoured but phrased loosely enough that a bare GW lookup is also a plausible (if incomplete) first move.",
    },
    {
        "id": "gw-11", "family": "gameweek_state", "control": True,
        "question": "¿Qué partidos hay programados para la fecha 12?",
        "acceptable_tools": ["get_fixtures_for_gw"],
        "note": "Explicit GW number + fixture list, same shape as gw-02/gw-07.",
    },
    {
        "id": "gw-12", "family": "gameweek_state", "control": True,
        "question": "¿Hay alguna fecha doble marcada en el calendario próximamente?",
        "acceptable_tools": ["get_gameweek_context"],
        "note": "Double-gameweek alert question, same shape as gw-03.",
    },
]

# ---------------------------------------------------------------------------
# chip_vs_gameweek -- the headline known-failure boundary.
#
# get_chip_advice vs get_gameweek_context. The pinned question is the exact
# verbatim case from the task brief, which splits 5/6 vs 1/6 in prior manual
# observation. get_gameweek_context is deliberately NOT in any acceptable set
# here -- it is the documented wrong pick, not a defensible alternative.
# build_squad is accepted alongside get_chip_advice only where the question
# explicitly asks to evaluate/build a squad from scratch, per build_squad's
# own schema text naming this exact scenario.
# ---------------------------------------------------------------------------
_CHIP_VS_GAMEWEEK: list[dict[str, Any]] = [
    {
        "id": "cvg-01", "family": "chip_vs_gameweek", "control": False, "pinned": True,
        "question": "evalúa mi equipo y qué tan buena idea es el bench boost en la fecha 2",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "PINNED verbatim from the task brief. Known baseline: get_gameweek_context wins 5/6.",
    },
    {
        "id": "cvg-02", "family": "chip_vs_gameweek", "control": False,
        "question": "¿Es buena idea usar el bench boost en la fecha 3? Analizá mi plantilla primero.",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Paraphrase of the pinned case: squad-eval framing + explicit GW number + bench_boost.",
    },
    {
        "id": "cvg-03", "family": "chip_vs_gameweek", "control": False,
        "question": "Quiero saber si conviene el bench boost esta fecha, evaluando cómo viene mi equipo.",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Same shape, relative GW reference instead of a number.",
    },
    {
        "id": "cvg-04", "family": "chip_vs_gameweek", "control": True,
        "question": "¿Debería usar el chip de bench boost en la próxima fecha?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Isolates the squad-eval framing: same chip+GW mention, NO 'evaluate my team' clause.",
    },
    {
        "id": "cvg-05", "family": "chip_vs_gameweek", "control": True,
        "question": "En la fecha 2, ¿me conviene tirar el bench boost?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Bare chip+GW-number question, no squad-eval framing -- isolates whether the GW number alone confuses.",
    },
    {
        "id": "cvg-06", "family": "chip_vs_gameweek", "control": False,
        "question": "Necesito armar mi equipo y decidir si vale la pena el bench boost para la fecha 4.",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Squad-build framing (not just 'evaluate') + chip + explicit GW number.",
    },
    {
        "id": "cvg-07", "family": "chip_vs_gameweek", "control": False,
        "question": "¿Qué tan viable es el free hit en la fecha 2 si arranco de cero con el equipo?",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Same shape as the pinned case with the chip swapped to free_hit.",
    },
    {
        "id": "cvg-08", "family": "chip_vs_gameweek", "control": False,
        "question": "Evaluá si conviene el wildcard en la fecha 3 armando el equipo desde cero.",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Chip swapped to wildcard, same squad-build + GW-number shape.",
    },
    {
        "id": "cvg-09", "family": "chip_vs_gameweek", "control": True,
        "question": "¿Vale la pena el triple captain en la fecha 2?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Chip+GW-number only, no squad-eval clause -- isolates GW-number effect with a different chip.",
    },
    {
        "id": "cvg-10", "family": "chip_vs_gameweek", "control": True,
        "question": "Fecha 2: ¿bench boost sí o no?",
        "acceptable_tools": ["get_chip_advice"],
        "note": "Terse, GW-number-leading phrasing with no squad-eval clause.",
    },
    {
        "id": "cvg-11", "family": "chip_vs_gameweek", "control": False,
        "question": "Mirá mi plantilla y decime si conviene el bench boost, estamos en la fecha 2.",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Squad-eval framing with the GW number stated as context rather than attached to the chip clause.",
    },
    {
        "id": "cvg-12", "family": "chip_vs_gameweek", "control": False,
        "question": "¿Bench boost en la fecha 2 es buena jugada evaluando mi equipo actual?",
        "acceptable_tools": ["get_chip_advice", "build_squad"],
        "note": "Closest single-sentence paraphrase of the pinned case, different word order.",
    },
]

CORPUS: list[dict[str, Any]] = (
    _TEAM_FIXTURES
    + _PLAYER_VIEWS
    + _CAPTAINCY
    + _SQUAD_BUILDING
    + _ADVICE
    + _GAMEWEEK_STATE
    + _CHIP_VS_GAMEWEEK
)

FAMILIES: tuple[str, ...] = (
    "team_fixtures",
    "player_views",
    "captaincy",
    "squad_building",
    "advice",
    "gameweek_state",
    "chip_vs_gameweek",
)

#: Tools this measurement deliberately excludes from every acceptable set
#: because they are environment-broken in a worktree, not product-broken.
#: See module docstring.
ZONAL_TOOLS: frozenset[str] = frozenset({
    "get_player_zonal_outlook",
    "get_zonal_opportunity",
    "get_zonal_weakness",
})


def get_pinned_question() -> dict[str, Any]:
    """Return the single pinned verbatim question from the task brief."""
    for entry in CORPUS:
        if entry.get("pinned"):
            return entry
    raise AssertionError("no pinned question found in corpus")
