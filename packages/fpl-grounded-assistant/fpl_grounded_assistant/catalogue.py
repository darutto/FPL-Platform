"""
fpl_grounded_assistant.catalogue
==================================
Language track, Phase F1: the ES/EN string catalogue.

A single, dependency-free lookup: ``t(key, locale, **params)``. No
``gettext``, no ``babel``, no ICU plural rules — this product has exactly two
locales and a bounded set of hand-written keys, and pulling in a translation
framework for that would be an abstraction with no second user.

No ambient state
-----------------
There is no module-global or ``contextvar`` "current locale" here, and there
must never be one. FastAPI runs sync endpoints in a threadpool; a global
would leak between concurrently-handled requests from different users and
produce a bug that shows up as "sometimes the wrong language" in production
and is nearly impossible to reproduce locally with a single caller. Every
call to ``t()`` takes ``locale`` explicitly, and every caller of ``t()``
must have received its own ``locale`` explicitly, all the way back to the
HTTP request boundary (``fpl_server.resolve_locale``). If a call site wants
to reach for ambient state instead of threading the parameter one level
further, that is the signal the parameter is missing, not that ambient state
is warranted.

The translation rule
---------------------
Applied consistently across every catalogue entry and every caller:

* **Never translated**: ``web_name``, club short codes (``LIV``, ``MCI``),
  position codes (``GKP``/``DEF``/``MID``/``FWD``), metric identifiers
  (``objective``, ``ranking_basis``, ``difficulty_label`` and other
  tool-computed enum values), and prices. These are identifiers and data,
  not prose — translating "MID" to a Spanish word would make the payload
  harder to cross-reference against the FPL API and the UI's own codes, not
  easier to read.
* **Translated**: gameweek → jornada, fixtures → partidos, budget →
  presupuesto, form → forma, owned → propiedad, and all connective prose
  around those values (headers, labels, fallback error text).
* Getting this line wrong — translating an identifier, or leaving connective
  prose in English — reads worse to a Spanish-speaking user than leaving the
  whole sentence in English, because it signals the product doesn't know its
  own vocabulary. When in doubt, leave the token alone and translate the
  words around it.

Tier boundary (see the renderer call sites, not this module)
--------------------------------------------------------------
This catalogue only ever supplies text that a *renderer* composes. A lot of
user-facing prose does not originate in a renderer at all — some tools
pre-build a finished sentence (``recommendation``, ``advice_text``,
``gw_note`` and similar fields) and the renderer just passes it through, and
some of it is FPL's own third-party API text (``news``). Neither of those
is reachable from here: a renderer that forwards ``output["recommendation"]``
verbatim will keep forwarding it verbatim regardless of locale, because the
string was never a catalogue lookup to begin with. That is expected, not a
bug in this module — see the F1 report for exactly which renderers still
leak English payload prose after this phase.

Failure behaviour
-------------------
A missing key or a template/params mismatch is a programming error, not a
runtime condition to route around. Under a test run (detected via
``"pytest" in sys.modules`` — no test-only import required) it raises
``CatalogueKeyError`` immediately, so a typo'd key or a forgotten format
parameter fails the test that exercises it. In production it logs the error
and degrades to the emptiest safe thing — never the raw key, which would
leak an internal identifier into a user-facing response — because a
half-missing translation is a smaller incident than a crashed request.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

try:
    from .locale_types import Locale, DEFAULT_LOCALE
except ImportError:  # standalone load (mirrors renderer.py's own fallback)
    from locale_types import Locale, DEFAULT_LOCALE  # type: ignore[no-redef]

_LOG = logging.getLogger(__name__)


class CatalogueKeyError(KeyError):
    """A catalogue lookup failed: unknown key, or a template/params mismatch."""


def _under_test() -> bool:
    # No test-only import: pytest registers itself in sys.modules as soon as
    # it starts, whether invoked as `pytest`, `python -m pytest`, or from an
    # IDE runner. Re-checked on every call (cheap dict lookup) rather than
    # cached at import time, since import order relative to pytest varies.
    return "pytest" in sys.modules


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
# Namespaced by renderer / call site. Each key maps locale -> format
# template. Every template is exercised by tests/test_es_en_catalogue_f1.py
# with representative params, so a bad `{placeholder}` fails loudly there
# rather than at request time.

_CATALOGUE: dict[str, dict[Locale, str]] = {
    # -- harness.py: the deterministic "no tool matched" fallback ----------
    "harness.unrecognised": {
        "en": (
            "The question could not be mapped to a known tool. "
            "Try asking 'Who is [player]?', 'Give me a summary for [player]', "
            "or 'What is the current gameweek?'."
        ),
        "es": (
            "No pude relacionar la pregunta con ninguna herramienta conocida. "
            "Probá preguntando '¿Quién es [jugador]?', "
            "'Dame un resumen de [jugador]', o '¿Cuál es la jornada actual?'."
        ),
    },

    # -- position noun, shared by any renderer that names a position group -
    "position_noun.GKP": {"en": "goalkeepers", "es": "porteros"},
    "position_noun.DEF": {"en": "defenders", "es": "defensas"},
    "position_noun.MID": {"en": "midfielders", "es": "mediocampistas"},
    "position_noun.FWD": {"en": "forwards", "es": "delanteros"},
    "position_noun.ALL": {"en": "all positions", "es": "todas las posiciones"},

    # -- get_transfer_suggestion --------------------------------------------
    "transfer_suggestion.header": {
        "en": "Top transfer targets — {team_prefix}{position_noun}{price_clause} (next {horizon} GWs):",
        "es": "Mejores fichajes — {team_prefix}{position_noun}{price_clause} (próximas {horizon} jornadas):",
    },
    "transfer_suggestion.price_clause": {
        "en": " under £{max_price}m",
        "es": " por debajo de £{max_price}m",
    },
    "transfer_suggestion.no_picks_suffix": {
        "en": " None found.",
        "es": " Ninguno encontrado.",
    },
    "transfer_suggestion.pick_line": {
        "en": (
            "  {rank}. {name} ({team}, {pos}) £{cost_m}m | form {form} "
            "| avg FDR {avg_fdr} ({label}) | {own}% owned"
        ),
        "es": (
            "  {rank}. {name} ({team}, {pos}) £{cost_m}m | forma {form} "
            "| FDR prom. {avg_fdr} ({label}) | {own}% propiedad"
        ),
    },
    "transfer_suggestion.empty_fallback": {
        "en": "No transfer targets found matching the criteria.",
        "es": "No se encontraron fichajes que cumplan esos criterios.",
    },
    "transfer_suggestion.not_found": {
        "en": (
            "No club matching '{team_query}' was found in the current fixture data. "
            "Check the spelling or try a common abbreviation (e.g. 'Liverpool', 'LIV', 'Spurs')."
        ),
        "es": (
            "No encontré ningún club que coincida con '{team_query}' en los datos de "
            "fixtures actuales. Revisá la ortografía o probá con una abreviatura "
            "común (por ejemplo, 'Liverpool', 'LIV', 'Spurs')."
        ),
    },
    "transfer_suggestion.missing_context_fallback": {
        "en": "Player data not available.",
        "es": "No hay datos de jugadores disponibles.",
    },
    "transfer_suggestion.error_fallback": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },

    # -- get_player_fixture_run ----------------------------------------------
    "player_fixture_run.header_suffix": {
        "en": " – next {horizon} fixture{plural}{gw_clause}:",
        "es": " – próximos {horizon} partido{plural}{gw_clause}:",
    },
    "player_fixture_run.gw_from_clause": {
        "en": " from GW{gw}",
        "es": " desde GW{gw}",
    },
    "player_fixture_run.fdr_context": {
        "en": " | {team} have {article} {label} run{gw_clause}, avg FDR {avg}.",
        "es": " | {team} tiene una racha {label}{gw_clause}, FDR prom. {avg}.",
    },
    "player_fixture_run.fdr_context_gw_clause": {
        "en": " over {gw_range}",
        "es": " entre {gw_range}",
    },
    "player_fixture_run.not_found_fallback": {
        "en": "Player not found.",
        "es": "Jugador no encontrado.",
    },
    "player_fixture_run.missing_context_fallback": {
        "en": "Fixture schedule not available.",
        "es": "Calendario de partidos no disponible.",
    },
    "player_fixture_run.error_fallback": {
        "en": "An unexpected fixture run error occurred.",
        "es": "Ocurrió un error inesperado al obtener el calendario de partidos.",
    },

    # -- compare_players -------------------------------------------------------
    # NOTE: the "ok" status text is almost entirely tier-2 (the tool's own
    # `recommendation` field, built in comparison.py) -- these three keys
    # are the only renderer-owned strings this renderer has.
    "compare_players.ok_fallback": {
        "en": "Comparison completed.",
        "es": "Comparación completada.",
    },
    "compare_players.not_found_fallback": {
        "en": "Could not resolve player '{player}'.",
        "es": "No pude identificar al jugador '{player}'.",
    },
    "compare_players.error_fallback": {
        "en": "An unexpected comparison error occurred.",
        "es": "Ocurrió un error inesperado al comparar jugadores.",
    },

    # -- get_player_snapshot -----------------------------------------------
    "player_snapshot.price_line": {
        "en": "  Price: £{cost}m | Owned: {own}% | Status: {status_lbl}",
        "es": "  Precio: £{cost}m | Propiedad: {own}% | Estado: {status_lbl}",
    },
    "player_snapshot.points_line": {
        "en": "  Total pts: {pts} | PPG: {ppg} | Form: {form}",
        "es": "  Pts totales: {pts} | PPG: {ppg} | Forma: {form}",
    },
    "player_snapshot.minutes_line": {
        "en": "  Minutes: {mins}",
        "es": "  Minutos: {mins}",
    },
    "player_snapshot.chance_line": {
        "en": "  Chance of playing: {chance}%",
        "es": "  Prob. de jugar: {chance}%",
    },
    "player_snapshot.news_line": {
        "en": "  News: {news}",
        "es": "  Noticias: {news}",
    },
    "player_snapshot.ambiguous_header": {
        "en": "Multiple players match '{query}' — please specify:",
        "es": "Múltiples jugadores coinciden con '{query}' — por favor especifica:",
    },
    "player_snapshot.candidate_line": {
        "en": "  - {name} ({team}, {pos}) [rank {rank}]",
        "es": "  - {name} ({team}, {pos}) [puesto {rank}]",
    },
    "player_snapshot.not_found_fallback": {
        "en": "Player not found.",
        "es": "Jugador no encontrado.",
    },
    "player_snapshot.error_fallback": {
        "en": "Unexpected error.",
        "es": "Error inesperado.",
    },

    # -- select_players_within_budget ---------------------------------------
    "select_players.header": {
        "en": "{count} {position} by {objective} (basis: {ranking_basis}):",
        "es": "{count} {position} por {objective} (base: {ranking_basis}):",
    },
    "select_players.column_header": {
        "en": "  Player           | Club | Price  | Value",
        "es": "  Jugador          | Club | Precio | Valor",
    },
    "select_players.locked_line": {
        "en": "  Already in the squad: {entries} — {locked_cost}m.",
        "es": "  Ya en el equipo: {entries} — {locked_cost}m.",
    },
    "select_players.selection_cost_line": {
        "en": (
            "  Selection cost: {selection_cost}m of {budget}m — {remaining}m left "
            "for the {slots_left} remaining slots."
        ),
        "es": (
            "  Coste de la selección: {selection_cost}m de {budget}m — queda "
            "{remaining}m para los {slots_left} huecos restantes."
        ),
    },
    "select_players.fits_line": {
        "en": (
            "  Fits: a legal 15 exists with these signings; the cheapest fill costs "
            "{cheapest_fill_cost}m (total {witness_total_cost}m). That fill is proof "
            "it fits, not a bench recommendation."
        ),
        "es": (
            "  Cabe: existe un 15 legal con estos fichajes; el relleno más barato "
            "cuesta {cheapest_fill_cost}m (total {witness_total_cost}m). Ese relleno "
            "es la prueba de que cabe, no una recomendación de banquillo."
        ),
    },
    "select_players.clubs_line": {
        "en": "  By club in the sample 15: {entries} (max allowed 3).",
        "es": "  Por club en el 15 de prueba: {entries} (máximo permitido 3).",
    },
    "select_players.warning_line": {
        "en": "  Warning: {warning}",
        "es": "  Aviso: {warning}",
    },
    "select_players.infeasible_fallback": {
        "en": "No legal selection exists under these constraints.",
        "es": "No hay ninguna selección legal con esas restricciones.",
    },
    "select_players.fits_entry_line": {
        "en": "  Does fit: {name} ({team}, {price}m)",
        "es": "  Sí cabe: {name} ({team}, {price}m)",
    },
    "select_players.ambiguous_fallback": {
        "en": "Multiple players match.",
        "es": "Varios jugadores coinciden.",
    },
    "select_players.ambiguous_candidates_suffix": {
        "en": "{message} Candidates: {candidates}.",
        "es": "{message} Candidatos: {candidates}.",
    },
    "select_players.not_found_fallback": {
        "en": "Could not find that player.",
        "es": "No encontré a ese jugador.",
    },
    "select_players.invalid_argument_fallback": {
        "en": "Invalid arguments for player selection.",
        "es": "Argumentos no válidos para seleccionar jugadores.",
    },
    "select_players.error_fallback": {
        "en": "Unexpected error.",
        "es": "Error inesperado.",
    },
}


def t(key: str, locale: Locale = DEFAULT_LOCALE, **params: Any) -> str:
    """Look up *key* for *locale* and format it with *params*.

    Never returns a raw catalogue key to the caller. A miss (unknown key, or
    a template that doesn't match the given *params*) raises
    :class:`CatalogueKeyError` under a test run, and degrades to an empty
    string in production after logging the error.
    """
    entry = _CATALOGUE.get(key)
    if entry is None:
        _LOG.error("catalogue: unknown key %r", key)
        if _under_test():
            raise CatalogueKeyError(f"unknown catalogue key: {key!r}")
        return ""

    template = entry.get(locale)
    if template is None:
        template = entry.get(DEFAULT_LOCALE)
    if template is None:
        _LOG.error("catalogue: key %r has no template for locale %r or default %r", key, locale, DEFAULT_LOCALE)
        if _under_test():
            raise CatalogueKeyError(f"catalogue key {key!r} has no usable template")
        return ""

    try:
        return template.format(**params)
    except (KeyError, IndexError) as exc:
        _LOG.error("catalogue: params mismatch for key %r locale %r: %s", key, locale, exc)
        if _under_test():
            raise CatalogueKeyError(
                f"params mismatch for catalogue key {key!r} locale {locale!r}: {exc}"
            ) from exc
        return ""
