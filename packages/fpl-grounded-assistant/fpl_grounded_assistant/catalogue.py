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
Applied consistently across every catalogue entry and every caller. The
discriminator is not "is this a tool-computed enum value" — ``difficulty_label``
is one and belongs on the translated side anyway (see below). The actual
question is:

    Does the user ever cross-reference this token against something else
    (the FPL app, another card, the raw API), or does it just read as a
    word inside a sentence?

* **Never translated — cross-referenced identifiers and data**: ``web_name``,
  club short codes (``LIV``, ``MCI``), position codes
  (``GKP``/``DEF``/``MID``/``FWD``), provenance/metric tags (``objective``,
  ``ranking_basis`` — e.g. ``current_season_partial``, snake_case and
  obviously a system token), and prices. A user cross-references ``MID`` and
  ``MCI`` against the FPL app; translating "MID" to a Spanish word would make
  the payload harder to line up against the app and the UI's own codes, not
  easier to read.
* **Translated — adjectives and connective prose, even when tool-computed**:
  gameweek → jornada, fixtures → partidos, budget → presupuesto, form →
  forma, owned → propiedad, ``difficulty_label`` (``easy``/``moderate``/
  ``hard``) → fácil/moderado/difícil, and all connective prose around these
  values (headers, labels, fallback error text). Nobody cross-references
  "easy" against anything; it is an adjective the renderer drops into a
  sentence, so it translates like the rest of the sentence around it —
  leaving it in English is what tripped this up the first time (see F1
  commit 3): ``"MCI tiene una racha easy"`` reads as broken, not neutral.
* Getting this line wrong — translating an identifier, or leaving an
  in-sentence adjective in English — reads worse to a Spanish-speaking user
  than leaving the whole sentence in English, because it signals the product
  doesn't know its own vocabulary. When in doubt, ask whether the token would
  ever be typed into a search box or matched against another system's output;
  if yes, leave it alone; if it only ever appears as a word inside a rendered
  sentence, translate it with the sentence.
* **Register — tuteo, not voseo.** Every second-person Spanish string uses
  "tú" verb forms (``revisa``, ``prueba``, ``usa``), never Rioplatense "vos"
  forms (``revisá``, ``probá``, ``usá``). This is a deliberate product-voice
  decision, not a per-string judgement call: a product that mixes tú and vos
  reads as two different products stitched together, so once one string picks
  a register every later string must match it rather than following whichever
  regional habit its author happens to have. Enforced by
  ``TestSpanishRegisterIsTuteo`` in the F1/F2 test module — any future string
  using a voseo verb form fails that test.

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
            "Prueba preguntando '¿Quién es [jugador]?', "
            "'Dame un resumen de [jugador]', o '¿Cuál es la jornada actual?'."
        ),
    },

    # -- orchestrator.py: the answer below is a deterministic render, not
    # prose the model wrote. i46: the synthesis call can come back with no
    # text at all (it asked for another tool instead), and the orchestrator
    # then falls back to render()ing the tool output. That fallback is worth
    # keeping -- a table beats nothing -- but shipping it unlabelled is what
    # made the defect read to users as a broken answer rather than a partial
    # one. Sits in this catalogue rather than inline because it is renderer
    # prose by every test that matters (it is prepended to render() output
    # and shares its locale), even though the call site is the orchestrator.
    # Wording note: "what the tool returned", not "the raw data". The same
    # notice fronts a raw table AND an already-readable tool error ("Metric
    # 'x' not recognized. Try: ..."), and calling that second one raw data
    # would make a good message read like a second failure. The alternative --
    # marking only some renders -- would mean deciding which renders are good
    # enough to pass as answers, which nobody has decided and which does not
    # belong in a fallback string.
    "orchestrator.raw_render_notice": {
        "en": "I couldn't compose an answer for this. Here is what the tool returned:",
        "es": "No pude redactar una respuesta para esto. Esto es lo que devolvió la herramienta:",
    },

    # -- i106: final-text guard. Said INSTEAD of a raw payload (a tool's
    # "Error (...)" line, an HTML page, a web_fetch dump), at the one point
    # every orchestrator result passes through. Names the tool, never the
    # payload; the blocked text goes to the audit line, not to the user.
    "orchestrator.final_text_guarded_tool": {
        "en": "I couldn't get a useful answer from {tool} for this. Try rephrasing or ask something else.",
        "es": "No obtuve una respuesta útil de {tool} para esto. Prueba a reformular o pregunta otra cosa.",
    },
    "orchestrator.final_text_guarded": {
        "en": "I couldn't get a useful answer for this. Try rephrasing or ask something else.",
        "es": "No obtuve una respuesta útil para esto. Prueba a reformular o pregunta otra cosa.",
    },

    # -- i18n S0: orchestrator fallbacks that used to be inline Spanish ------
    "orchestrator.no_tool_found": {
        "en": "I couldn't find a tool to answer that.",
        "es": "No encontré una herramienta para responder a esto.",
    },
    "orchestrator.tool_call_failed": {
        "en": "A tool call could not be completed.",
        "es": "No se pudo completar una llamada de herramienta correctamente.",
    },
    "orchestrator.tool_call_failed_reason": {
        "en": "A tool call could not be completed ({reason}).",
        "es": "No se pudo completar una llamada de herramienta correctamente ({reason}).",
    },
    "orchestrator.incomplete_answer": {
        "en": "Incomplete answer ({reason}): {rendered}",
        "es": "Respuesta incompleta ({reason}): {rendered}",
    },

    # -- i18n S3: advantage phrases shared by the comparison and the transfer
    # cards (one source, both cards). es is what comparison.py / transfer_advisor.py
    # / scoring_shared.py said inline; the venue letters are the cards' L/V.
    "advantage.form": {
        "en": "better form ({a} vs {b})",
        "es": "mejor forma ({a} vs {b})",
    },
    "advantage.easier_fixture": {
        "en": "easier fixture (FDR {a}{av} vs {b}{bv})",
        "es": "partido más fácil (FDR {a}{av} vs {b}{bv})",
    },
    "advantage.xgi": {"en": "higher xGI per 90", "es": "más xGI por 90"},
    "advantage.minutes": {"en": "more secure minutes", "es": "minutos más asegurados"},
    "advantage.set_piece": {"en": "set-piece advantage", "es": "ventaja a balón parado"},
    "advantage.venue_home": {"en": "H", "es": "L"},
    "advantage.venue_away": {"en": "A", "es": "V"},
    "advantage.clause": {
        "en": "  Advantages: {reasons}.",
        "es": "  Ventajas: {reasons}.",
    },
    "set_piece_short.penalty_taker_1": {"en": "penalties", "es": "penales"},
    "set_piece_short.penalty_taker_2": {"en": "2nd on penalties", "es": "2.º en penales"},
    "set_piece_short.freekick_taker_1": {"en": "free kicks", "es": "tiros libres"},
    "set_piece_short.freekick_taker_2": {"en": "2nd on free kicks", "es": "2.º en tiros libres"},

    # -- comparison.py: the recommendation sentence (served as the answer text
    # on the deterministic path, and carrying the reasons above).
    "comparison.tie": {
        "en": "{a} ({sa}) and {b} ({sb}) are level on score.",
        "es": "{a} ({sa}) y {b} ({sb}) empatan en puntuación.",
    },
    "comparison.beats": {
        "en": "{winner} ({ws}) beats {loser} ({ls}) — {label} margin ({margin}).",
        "es": "{winner} ({ws}) supera a {loser} ({ls}) — diferencia {label} ({margin}).",
    },
    "comparison.margin.narrow": {"en": "narrow", "es": "ajustada"},
    "comparison.margin.moderate": {"en": "moderate", "es": "moderada"},
    "comparison.margin.clear": {"en": "clear", "es": "clara"},

    # -- transfer_advisor.py: the recommendation sentence.
    "transfer.price_cost": {"en": "  Net cost: +£{m}m.", "es": "  Coste neto: +£{m}m."},
    "transfer.price_saving": {"en": "  Net saving: £{m}m.", "es": "  Ahorro neto: £{m}m."},
    "transfer.rec_in": {
        "en": "Recommendation: bring in {inn}. Score: {si} vs {so} for {out} (+{d}).{reasons}{price}",
        "es": "Recomendación: incorpora a {inn}. Puntuación: {si} vs {so} de {out} (+{d}).{reasons}{price}",
    },
    "transfer.rec_marginal": {
        "en": "Close call: consider {inn} instead of {out}. Score: {si} vs {so} (+{d}).{reasons}{price}",
        "es": "Ajustado: valora a {inn} en lugar de {out}. Puntuación: {si} vs {so} (+{d}).{reasons}{price}",
    },
    "transfer.rec_hold": {
        "en": "Recommendation: keep {out}. Score: {so} vs {si} for {inn} ({d}).{reasons}",
        "es": "Recomendación: mantén a {out}. Puntuación: {so} vs {si} de {inn} ({d}).{reasons}",
    },

    # -- i18n S3b: generic_card labels (titles, pills, column headers, FDR bands).
    # es is what generic_card.py said inline. The injury column headers keep the
    # UI adapter's keyword vocabulary (InjuryListTable HEADER_MATCHERS already
    # accepts player/team/pos/status/chance/news/date).
    "gcard.fdr.1": {"en": "Very favourable", "es": "Muy favorable"},
    "gcard.fdr.2": {"en": "Favourable", "es": "Favorable"},
    "gcard.fdr.3": {"en": "Average", "es": "Media"},
    "gcard.fdr.4": {"en": "Tough", "es": "Exigente"},
    "gcard.fdr.5": {"en": "Very tough", "es": "Muy exigente"},
    "gcard.venue.home": {"en": "Home", "es": "Casa"},
    "gcard.venue.away": {"en": "Away", "es": "Fuera"},
    "gcard.form.title": {"en": "RECENT FORM", "es": "FORMA RECIENTE"},
    "gcard.form.hero": {"en": "POINTS \u00b7 {n} GW", "es": "PUNTOS \u00b7 {n} JOR"},
    "gcard.form.col_gw": {"en": "GW", "es": "JOR"},
    "gcard.price.title": {"en": "PRICE CHANGES", "es": "CAMBIOS DE PRECIO"},
    "gcard.price.rising": {"en": "{n} RISING", "es": "{n} SUBEN"},
    "gcard.price.falling": {"en": "{n} FALLING", "es": "{n} BAJAN"},
    "gcard.col.player": {"en": "PLAYER", "es": "JUGADOR"},
    "gcard.col.team": {"en": "TEAM", "es": "EQUIPO"},
    "gcard.col.price": {"en": "PRICE", "es": "PRECIO"},
    "gcard.col.change": {"en": "CHANGE", "es": "CAMBIO"},
    "gcard.cal.title": {"en": "FIXTURES", "es": "CALENDARIO"},
    "gcard.cal.title_position": {"en": "FIXTURES BY POSITION", "es": "CALENDARIO POR POSICI\u00d3N"},
    "gcard.cal.mode.easiest": {"en": "Most favourable fixtures", "es": "Calendario m\u00e1s favorable"},
    "gcard.cal.mode.hardest": {"en": "Toughest fixtures", "es": "Calendario m\u00e1s exigente"},
    "gcard.cal.horizon": {"en": "{n} GAMEWEEKS", "es": "{n} JORNADAS"},
    "gcard.cal.col_fixtures": {"en": "FIXTURES", "es": "PARTIDOS"},
    "gcard.cal.col_avg_fdr": {"en": "AVG FDR", "es": "FDR MEDIO"},
    "gcard.cal.col_difficulty": {"en": "DIFFICULTY", "es": "DIFICULTAD"},
    "gcard.sched.fixtures": {"en": "{n} FIXTURES", "es": "{n} PARTIDOS"},
    "gcard.sched.dgw": {"en": "DOUBLE GAMEWEEK", "es": "DOBLE JORNADA"},
    "gcard.sched.bgw": {"en": "BLANK GAMEWEEK", "es": "JORNADA EN BLANCO"},
    "gcard.sched.col_gw": {"en": "GW", "es": "JOR"},
    "gcard.sched.col_opp": {"en": "OPP", "es": "RIVAL"},
    "gcard.sched.col_venue": {"en": "VENUE", "es": "SEDE"},
    "gcard.gw.title": {"en": "CURRENT GAMEWEEK", "es": "JORNADA ACTUAL"},
    "gcard.gw.hero": {"en": "GAMEWEEK IN PROGRESS", "es": "JORNADA EN CURSO"},
    "gcard.inj.title": {"en": "INJURIES", "es": "LESIONES"},
    "gcard.inj.injured": {"en": "{n} INJURED", "es": "{n} LESIONADOS"},
    "gcard.inj.doubtful": {"en": "{n} DOUBTFUL", "es": "{n} EN DUDA"},
    "gcard.inj.unavailable": {"en": "{n} UNAVAILABLE", "es": "{n} NO DISPONIBLES"},
    "gcard.inj.col_status": {"en": "STATUS", "es": "ESTADO"},
    "gcard.inj.col_chance": {"en": "CHANCE %", "es": "PROBABILIDAD %"},
    "gcard.inj.col_news": {"en": "NEWS", "es": "NOTICIA"},
    "gcard.inj.col_date": {"en": "DATE", "es": "FECHA"},

    # -- i18n S3b: needs_clarification prompts (final_response). The en side is
    # the wording these had before (they were English-only, so a Spanish user
    # saw English); es is new, tuteo, opportunity framing (no buy/sell words).
    "clarify.captain": {
        "en": (
            "Are you looking for captaincy advice or player rankings for this gameweek? "
            "Try asking 'who should I captain?' or 'best captain options'."
        ),
        "es": (
            "\u00bfBuscas consejo de capitan\u00eda o un ranking de jugadores para esta jornada? "
            "Prueba con '\u00bfa qui\u00e9n capitaneo?' o 'mejores opciones de capit\u00e1n'."
        ),
    },
    "clarify.compare": {
        "en": "Are you comparing two players? Try asking 'compare [Player A] vs [Player B]'.",
        "es": "\u00bfQuieres comparar a dos jugadores? Prueba con 'compara [Jugador A] vs [Jugador B]'.",
    },
    "clarify.transfer": {
        "en": (
            "Are you looking for transfer suggestions? "
            "Try asking 'who should I transfer in?' or 'best players to buy under \u00a38m'."
        ),
        "es": (
            "\u00bfBuscas ideas para mejorar tu plantilla? "
            "Prueba con '\u00bfa qui\u00e9n incorporo?' o 'mejores jugadores por menos de \u00a38m'."
        ),
    },
    "clarify.form": {
        "en": (
            "Are you asking about a player's recent form? "
            "Try asking 'how has [player] been playing?' or 'stats for [player] last 5 games'."
        ),
        "es": (
            "\u00bfPreguntas por la forma reciente de un jugador? "
            "Prueba con '\u00bfc\u00f3mo est\u00e1 jugando [jugador]?' o 'estad\u00edsticas de [jugador] en los \u00faltimos 5 partidos'."
        ),
    },
    "clarify.player_fixture_run": {
        "en": "Are you asking about a player's upcoming fixtures? Try 'upcoming fixtures for [player]'.",
        "es": "\u00bfPreguntas por los pr\u00f3ximos partidos de un jugador? Prueba con 'pr\u00f3ximos partidos de [jugador]'.",
    },
    "clarify.injury": {
        "en": "Are you asking about injuries or availability? Try 'who is injured this gameweek?'.",
        "es": "\u00bfPreguntas por lesiones o disponibilidad? Prueba con '\u00bfqui\u00e9n est\u00e1 lesionado esta jornada?'.",
    },
    "clarify.price": {
        "en": "Are you asking about price changes? Try 'who has gone up in price?' or 'recent price risers'.",
        "es": "\u00bfPreguntas por cambios de precio? Prueba con '\u00bfqui\u00e9n ha subido de precio?' o '\u00faltimas subidas de precio'.",
    },
    "clarify.chip": {
        "en": (
            "Are you asking about when to use a chip? "
            "Try 'should I use my wildcard?' or 'when should I use my bench boost?'."
        ),
        "es": (
            "\u00bfPreguntas por cu\u00e1ndo usar un chip? "
            "Prueba con '\u00bfdebo usar mi Wildcard?' o '\u00bfcu\u00e1ndo uso mi Bench Boost?'."
        ),
    },
    "clarify.differential": {
        "en": "Are you looking for differential picks? Try 'low-ownership players worth picking'.",
        "es": "\u00bfBuscas diferenciales? Prueba con 'jugadores de baja propiedad que merezcan la pena'.",
    },
    "clarify.calendar": {
        "en": "Are you looking at fixture difficulty? Try 'which teams have the best fixtures coming up?'.",
        "es": "\u00bfMiras la dificultad de los partidos? Prueba con '\u00bfqu\u00e9 equipos tienen mejor calendario?'.",
    },
    "clarify.suggestion": {
        "en": (
            "Are you looking for specific player recommendations? "
            "Try 'best midfielders under \u00a37m' or 'top Arsenal players to buy'."
        ),
        "es": (
            "\u00bfBuscas recomendaciones de jugadores concretos? "
            "Prueba con 'mejores centrocampistas por menos de \u00a37m' o 'mejores jugadores del Arsenal'."
        ),
    },
    "clarify.fallback": {
        "en": (
            "I'm not sure what you're looking for. "
            "Try rephrasing \u2014 for example, 'who should I captain?' or 'compare Saka vs Palmer'."
        ),
        "es": (
            "No estoy seguro de qu\u00e9 buscas. "
            "Prueba a reformularlo, por ejemplo '\u00bfa qui\u00e9n capitaneo?' o 'compara Saka vs Palmer'."
        ),
    },

    # -- i18n S5a: renderer.py inline answer text. es is what renderer.py said
    # inline (byte-for-byte); en is new except for the rank_captain strings that
    # already had an inline English branch. Param values are pre-formatted by the
    # caller so the number formatting stays where it was.
    "renderer.error_unexpected": {"en": "Unexpected error.", "es": "Error inesperado."},
    # fallbacks shown only when a tool result carries no message of its own
    "renderer.fallback.error": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },
    "renderer.fallback.chip_error": {
        "en": "An unexpected chip advice error occurred.",
        "es": "Ocurrió un error inesperado con el consejo de chips.",
    },
    "renderer.fallback.transfer_error": {
        "en": "An unexpected transfer advice error occurred.",
        "es": "Ocurrió un error inesperado con el consejo de traspasos.",
    },
    "renderer.fallback.form_unavailable": {
        "en": "Player match history unavailable.",
        "es": "El historial de partidos del jugador no está disponible.",
    },
    "renderer.fallback.form_error": {
        "en": "An unexpected player form error occurred.",
        "es": "Ocurrió un error inesperado con la forma del jugador.",
    },
    "renderer.fallback.season_points_error": {
        "en": "An unexpected error occurred looking up season points.",
        "es": "Ocurrió un error inesperado al buscar los puntos de la temporada.",
    },
    "renderer.fallback.price_none": {
        "en": "No price-change data available.",
        "es": "No hay datos de cambios de precio.",
    },
    "renderer.fallback.price_error": {
        "en": "An unexpected price changes error occurred.",
        "es": "Ocurrió un error inesperado con los cambios de precio.",
    },
    "renderer.fallback.schedule_unavailable": {
        "en": "Fixture schedule data not available.",
        "es": "El calendario de partidos no está disponible.",
    },
    "renderer.fallback.unknown_position": {
        "en": "Unknown position.",
        "es": "Posición desconocida.",
    },
    "renderer.fallback.team_not_found": {
        "en": "Team not found.",
        "es": "Equipo no encontrado.",
    },
    "renderer.fallback.no_player": {
        "en": "No player found matching '{query}'.",
        "es": "No se encontró ningún jugador que coincida con '{query}'.",
    },
    "renderer.fallback.resolve_player": {
        "en": "Could not resolve player '{ep}'.",
        "es": "No se pudo identificar al jugador '{ep}'.",
    },
    # differential picks (the rows keep the FPL price format: £x.xm)
    "renderer.differentials.header": {
        "en": "Top differentials (ownership < {threshold}%):",
        "es": "Mejores diferenciales (propiedad < {threshold}%):",
    },
    "renderer.differentials.none": {
        "en": "No differential picks found (ownership < {threshold}%).",
        "es": "No se encontraron diferenciales (propiedad < {threshold}%).",
    },
    "renderer.differentials.empty": {
        "en": "No differential picks found.",
        "es": "No se encontraron diferenciales.",
    },
    "renderer.differentials.error": {
        "en": "An unexpected differential picks error occurred.",
        "es": "Ocurrió un error inesperado al buscar diferenciales.",
    },
    "renderer.differentials.row": {
        "en": "  {rank}. {name} ({team}, {position}) — score {score}, {owned}% owned, £{cost}m",
        "es": "  {rank}. {name} ({team}, {position}) — puntuación {score}, {owned}% de propiedad, £{cost}m",
    },
    "renderer.captain.pool_derived": {
        "en": "Pool source: derived from bootstrap.",
        "es": "Origen del pool: derivado del bootstrap.",
    },
    "renderer.captain.pool_caller": {
        "en": "Pool source: caller-supplied candidates.",
        "es": "Origen del pool: candidatos indicados por el usuario.",
    },
    "renderer.captain.no_hipster": {
        "en": "No hipster: nobody lightly owned clears the bar.",
        "es": "Sin hipster: nadie de poca propiedad llega al minimo.",
    },
    "renderer.captain.share": {"en": " - owned by {v}%", "es": " - {v}% de propiedad"},
    "renderer.captain.your_squad": {"en": " \u00b7 your squad", "es": " \u00b7 tu plantilla"},
    "renderer.captain.owned_header": {
        "en": "A) Candidates from your squad:",
        "es": "A) Candidatos de tu plantilla:",
    },
    "renderer.captain.owned_none": {
        "en": "There are no available candidates in your squad.",
        "es": "No hay candidatos disponibles en tu plantilla.",
    },
    "renderer.captain.squad_unavailable": {
        "en": "I could not load your squad, so I am showing only the global ranking.",
        "es": "No pude cargar tu plantilla; te muestro solo el ranking global.",
    },
    "renderer.captain.not_connected": {
        "en": "No team is connected, so I am showing only the global ranking.",
        "es": "No hay equipo conectado; te muestro solo el ranking global.",
    },
    "renderer.captain.excl_unavailable": {"en": "unavailable", "es": "no disponible"},
    "renderer.captain.excl_unresolved": {"en": "unresolved", "es": "sin resolver"},
    "renderer.captain.not_evaluated": {
        "en": "Not evaluated for captaincy: {items}.",
        "es": "No evaluados para capitan\u00eda: {items}.",
    },
    "renderer.captain.global_header": {
        "en": "B) Best global candidates:",
        "es": "B) Mejores candidatos globales:",
    },
    "renderer.captain.worth_knowing": {"en": "Worth knowing: {line}", "es": "Conviene saber: {line}"},
    "renderer.captain.about": {"en": "On {name}: {note}", "es": "Sobre {name}: {note}"},

    "renderer.team_results.header": {
        "en": "{name} \u2014 last {n} matches{venue}:",
        "es": "{name} \u2014 \u00faltimos {n} partidos{venue}:",
    },
    "renderer.team_results.venue_home": {"en": " at home", "es": " de local"},
    "renderer.team_results.venue_away": {"en": " away", "es": " de visitante"},
    "renderer.team_results.where_home": {"en": "vs", "es": "vs"},
    "renderer.team_results.where_away": {"en": "at", "es": "en casa de"},
    "renderer.team_results.gw": {"en": "GW{gw} ", "es": "J{gw} "},
    "renderer.team_results.summary": {
        "en": "Summary: {line}.",
        "es": "Resumen: {line}.",
    },
    "renderer.team_results.home": {"en": "Home: {line}.", "es": "Local: {line}."},
    "renderer.team_results.away": {"en": "Away: {line}.", "es": "Visitante: {line}."},
    "renderer.team_results.line": {
        "en": (
            "{played} P, {won}W {drawn}D {lost}L, GF {gf} GA {ga}, {cs} clean sheets "
            "(avg {avg_gf} for / {avg_ga} against)"
        ),
        "es": (
            "{played} PJ, {won}G {drawn}E {lost}P, GF {gf} GC {ga}, {cs} porter\u00edas a cero "
            "(media {avg_gf} a favor / {avg_ga} en contra)"
        ),
    },
    "renderer.team_results.ambiguous": {
        "en": "'{query}' matches several teams.",
        "es": "'{query}' coincide con varios equipos.",
    },
    "renderer.team_results.not_found": {
        "en": "I couldn't find the team '{query}'.",
        "es": "No encontr\u00e9 el equipo '{query}'.",
    },
    "renderer.team_results.error": {
        "en": "Unexpected error while fetching the team's results.",
        "es": "Error inesperado al consultar los resultados del equipo.",
    },

    "renderer.top_scorer.none": {
        "en": "No finished gameweeks for season {season}.",
        "es": "Sin datos de jornadas terminadas para la temporada {season}.",
    },
    "renderer.top_scorer.points": {"en": "{pts} points", "es": "{pts} puntos"},
    "renderer.top_scorer.no_points": {"en": "points not available", "es": "puntos no disponibles"},
    "renderer.top_scorer.single": {
        "en": "Player of gameweek {gw} ({season}): {line}.",
        "es": "Jugador de la jornada {gw} ({season}): {line}.",
    },
    "renderer.top_scorer.season_header": {
        "en": "Player of the gameweek, season {season}:",
        "es": "Jugador de la jornada, temporada {season}:",
    },
    "renderer.top_scorer.row_gw": {"en": "GW{gw}: {line}", "es": "J{gw}: {line}"},
    "renderer.top_scorer.not_finished": {
        "en": "Gameweek {gw} of {season} has not finished yet.",
        "es": "La jornada {gw} de {season} a\u00fan no ha terminado.",
    },
    "renderer.top_scorer.not_found": {
        "en": "I found no data for that gameweek or season.",
        "es": "No encontr\u00e9 datos para esa jornada o temporada.",
    },
    "renderer.top_scorer.invalid": {"en": "Invalid argument.", "es": "Argumento inv\u00e1lido."},
    "renderer.top_scorer.error": {
        "en": "An unexpected error occurred while reading the history.",
        "es": "Ocurri\u00f3 un error inesperado consultando el hist\u00f3rico.",
    },

    "renderer.find_players.header": {
        "en": "Players found for '{query}':",
        "es": "Jugadores encontrados para '{query}':",
    },
    "renderer.find_players.row": {
        "en": "  - {name} ({team}, {pos}) \u2014 \u00a3{cost}m | Form {form} | {pts}pts | Mins {mins}",
        "es": "  - {name} ({team}, {pos}) \u2014 \u00a3{cost}m | Forma {form} | {pts}pts | Mins {mins}",
    },
    "renderer.find_players.not_found": {
        "en": "No player found matching '{query}'.",
        "es": "No se encontr\u00f3 ning\u00fan jugador que coincida con '{query}'.",
    },

    "renderer.history.header": {
        "en": "{name} ({team}, {pos}) \u2014 last {n} gameweek(s):",
        "es": "{name} ({team}, {pos}) \u2014 \u00faltimas {n} jornada(s):",
    },
    "renderer.history.empty": {"en": " No history available.", "es": " Sin historial disponible."},
    "renderer.history.table": {
        "en": "  GW  | Opp   | Mins | Pts | G | A  | xG   | xA",
        "es": "  GW  | Rival | Mins | Pts | G | A  | xG   | xA",
    },
    "renderer.history.summary": {
        "en": "\n  Summary: {pts}pts total | Average form: {avg} | Total xGI: {xgi}",
        "es": "\n  Resumen: {pts}pts totales | Forma media: {avg} | xGI total: {xgi}",
    },
    "renderer.history.ambiguous": {
        "en": "Multiple players match \u2014 please give the full name.",
        "es": "M\u00faltiples jugadores coinciden \u2014 especifica el nombre.",
    },
    "renderer.history.not_found": {"en": "Player not found.", "es": "Jugador no encontrado."},

    "renderer.fixtures_gw.blank": {
        "en": "\u26a0 Blank gameweek (a team has no fixture)",
        "es": "\u26a0 Jornada en blanco (alg\u00fan equipo sin partido)",
    },
    "renderer.fixtures_gw.double": {
        "en": "\u26a0 Double gameweek \u2014 teams with 2 fixtures: {teams}",
        "es": "\u26a0 Jornada doble \u2014 equipos con 2 partidos: {teams}",
    },
    "renderer.fixtures_gw.header": {"en": "Fixtures GW{gw}:", "es": "Partidos GW{gw}:"},
    "renderer.fixtures_gw.row": {
        "en": "  GW{gw}: {home} vs {away} (kickoff: {ko}) | FDR home {h}, FDR away {a}",
        "es": "  GW{gw}: {home} vs {away} (kickoff: {ko}) | FDR local {h}, FDR visit {a}",
    },
    "renderer.fixtures_gw.none": {
        "en": "  No fixtures for this gameweek.",
        "es": "  Sin partidos para esta jornada.",
    },
    "renderer.fixtures_gw.bgw_teams": {
        "en": "  Teams without a fixture (BGW): {teams}",
        "es": "  Equipos sin partido (BGW): {teams}",
    },
    "renderer.fixtures_gw.out_of_range": {
        "en": "Gameweek number out of range (1-38).",
        "es": "N\u00famero de jornada fuera de rango (1-38).",
    },

    "renderer.gw_context.season_over": {"en": "The season is over.", "es": "La temporada ha finalizado."},
    "renderer.gw_context.line": {
        "en": "Current gameweek: GW{curr} ({status}). Next gameweek: {next}.",
        "es": "Jornada actual: GW{curr} ({status}). Pr\u00f3xima jornada: {next}.",
    },
    "renderer.gw_context.blank": {
        "en": "  \u2022 BGW{gw}: teams without a fixture \u2014 {teams}",
        "es": "  \u2022 BGW{gw}: equipos sin partido \u2014 {teams}",
    },
    "renderer.gw_context.double": {
        "en": "  \u2022 DGW{gw}: teams with a double fixture \u2014 {teams}",
        "es": "  \u2022 DGW{gw}: equipos con doble partido \u2014 {teams}",
    },
    "renderer.gw_context.error": {
        "en": "Error getting the gameweek context.",
        "es": "Error obteniendo contexto de jornada.",
    },

    "renderer.team_snapshot.run_easy": {"en": "easy", "es": "f\u00e1cil"},
    "renderer.team_snapshot.run_hard": {"en": "tough", "es": "dura"},
    "renderer.team_snapshot.run_mid": {"en": "average", "es": "media"},
    "renderer.team_snapshot.header": {
        "en": "**{name} ({short})** \u2014 {run} run (average FDR: {avg})",
        "es": "**{name} ({short})** \u2014 racha {run} (FDR medio: {avg})",
    },
    "renderer.team_snapshot.fixtures": {"en": "  Upcoming fixtures:", "es": "  Pr\u00f3ximos partidos:"},
    "renderer.team_snapshot.top_players": {
        "en": "  Top players (by points):",
        "es": "  Mejores jugadores (por puntos):",
    },
    "renderer.team_snapshot.player_row": {
        "en": "    {name} ({pos}) \u2014 {pts}pts | form {form} | \u00a3{cost}m",
        "es": "    {name} ({pos}) \u2014 {pts}pts | forma {form} | \u00a3{cost}m",
    },
    "renderer.team_snapshot.leaders": {
        "en": "  Top scorer: {scorer} | Best form: {form}",
        "es": "  M\u00e1ximo goleador: {scorer} | Mejor forma: {form}",
    },
    "renderer.team_snapshot.ambiguous": {
        "en": "Multiple teams match '{query}': {shorts}. Please be more specific.",
        "es": "M\u00faltiples equipos coinciden con '{query}': {shorts}. Por favor especifica.",
    },
    "renderer.team_snapshot.not_found": {"en": "Team not found.", "es": "Equipo no encontrado."},

    "renderer.web.error": {
        "en": "The web search could not be completed.",
        "es": "No se pudo completar la b\u00fasqueda web.",
    },
    "renderer.web.none": {
        "en": "I found no relevant results for that search.",
        "es": "No encontr\u00e9 resultados relevantes para esa b\u00fasqueda.",
    },
    "renderer.web.found": {"en": "Here is what I found on the web:", "es": "Esto encontr\u00e9 en la web:"},
    "renderer.fetch.ok": {
        "en": "Fetched {url} ({length} bytes{trunc}).\n{excerpt}",
        "es": "Obtenido {url} ({length} bytes{trunc}).\n{excerpt}",
    },
    "renderer.fetch.truncated": {"en": " (truncated)", "es": " (truncado)"},
    "renderer.fetch.refused": {
        "en": "URL rejected by the allowed-domains list.",
        "es": "URL rechazada por la lista de dominios permitidos.",
    },
    "renderer.fetch.error": {"en": "Error fetching the URL.", "es": "Error al obtener la URL."},

    "renderer.metric.pos_filter": {"en": "position: {pos}", "es": "posici\u00f3n: {pos}"},
    "renderer.metric.min_minutes": {"en": "min. minutes: {n}", "es": "min. minutos: {n}"},
    "renderer.metric.none": {
        "en": "No players for the metric '{metric}'{filters}.",
        "es": "Sin jugadores para la m\u00e9trica '{metric}'{filters}.",
    },
    "renderer.metric.inverted_asc": {
        "en": "The {n} players with the lowest {metric}{filters}:",
        "es": "Los {n} jugadores con menor {metric}{filters}:",
    },
    "renderer.metric.inverted_desc": {
        "en": "The {n} players with the highest {metric}{filters}:",
        "es": "Los {n} jugadores con mayor {metric}{filters}:",
    },
    "renderer.metric.top": {
        "en": "Top {n} players by {metric}{filters}:",
        "es": "Top {n} jugadores por {metric}{filters}:",
    },
    "renderer.metric.table": {
        "en": "  #  | Player        | Team   | Pos | Metric value",
        "es": "  #  | Jugador       | Equipo | Pos | Valor m\u00e9trica",
    },
    "renderer.metric.unknown": {"en": "Metric not recognised.", "es": "M\u00e9trica no reconocida."},

    "renderer.squad.header": {
        "en": "Squad of {n} players by {objective} (basis: {basis}):",
        "es": "Equipo de {n} jugadores por {objective} (base: {basis}):",
    },
    "renderer.squad.table": {
        "en": "  Pos | Player           | Club | Price  | Value  | XI",
        "es": "  Pos | Jugador          | Club | Precio | Valor  | XI",
    },
    "renderer.squad.bench": {"en": "bench", "es": "banca"},
    "renderer.squad.total": {
        "en": "  Total cost: {cost}m of {budget}m \u2014 {remaining}m left.",
        "es": "  Coste total: {cost}m de {budget}m \u2014 queda {remaining}m.",
    },
    "renderer.squad.clubs": {
        "en": "  Per club: {clubs} (maximum allowed {max}).",
        "es": "  Por club: {clubs} (m\u00e1ximo permitido {max}).",
    },
    "renderer.squad.formation": {
        "en": "  Formation: {formation} (plus goalkeeper).",
        "es": "  Alineaci\u00f3n: {formation} (m\u00e1s portero).",
    },
    "renderer.squad.warning": {"en": "  Note: {warning}", "es": "  Aviso: {warning}"},
    "renderer.squad.infeasible": {
        "en": "No legal squad exists with those constraints.",
        "es": "No existe ning\u00fan equipo legal con esas restricciones.",
    },
    "renderer.squad.ambiguous": {"en": "Several players match.", "es": "Varios jugadores coinciden."},
    "renderer.squad.candidates": {"en": "{message} Candidates: {names}.", "es": "{message} Candidatos: {names}."},
    "renderer.squad.not_found": {"en": "I couldn't find that player.", "es": "No encontr\u00e9 a ese jugador."},
    "renderer.squad.invalid": {
        "en": "Invalid arguments for building the squad.",
        "es": "Argumentos no v\u00e1lidos para armar el equipo.",
    },

    # -- i18n S5a: generic orchestrator failure texts. en is the wording these had;
    # they were English-only, so a Spanish user saw English -- es is new (deliberate
    # behaviour change, same call as the clarification prompts in S3b).
    "orch_err.llm_failed": {
        "en": "LLM call failed during orchestration.",
        "es": "Falló la llamada al modelo durante la orquestación.",
    },
    "orch_err.auth_failed": {
        "en": "LLM authentication failed during orchestration.",
        "es": "Falló la autenticación con el modelo durante la orquestación.",
    },
    "orch_err.no_client": {
        "en": "No LLM client available for orchestration.",
        "es": "No hay un cliente de modelo disponible para la orquestación.",
    },
    "orch_err.cooldown": {
        "en": "LLM provider temporarily unavailable (cooldown active).",
        "es": "El proveedor del modelo no está disponible por el momento (enfriamiento activo).",
    },
    "orch_err.unknown_tool": {
        "en": "Model selected an unknown tool: {tool}.",
        "es": "El modelo eligió una herramienta desconocida: {tool}.",
    },
    "orch_err.tool_raised": {
        "en": "Tool execution raised an error for {tool}.",
        "es": "La ejecución de la herramienta falló para {tool}.",
    },

    # -- position noun, shared by any renderer that names a position group -
    "position_noun.GKP": {"en": "goalkeepers", "es": "porteros"},
    "position_noun.DEF": {"en": "defenders", "es": "defensas"},
    "position_noun.MID": {"en": "midfielders", "es": "mediocampistas"},
    "position_noun.FWD": {"en": "forwards", "es": "delanteros"},
    "position_noun.ALL": {"en": "all positions", "es": "todas las posiciones"},

    # -- difficulty_label, shared by get_transfer_suggestion and
    # get_player_fixture_run (the same closed 3-value enum, same thresholds:
    # transfer_suggestion.py's _difficulty_label() and
    # player_fixture_run.py's fdr context builder). An adjective dropped
    # into a sentence, not a cross-referenced identifier -- see the
    # translation rule above. F1 commit 3.
    "difficulty_label.easy": {"en": "easy", "es": "fácil"},
    "difficulty_label.moderate": {"en": "moderate", "es": "moderado"},
    "difficulty_label.hard": {"en": "hard", "es": "difícil"},

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
            "fixtures actuales. Revisa la ortografía o prueba con una abreviatura "
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
    "compare_players.ambiguous": {
        "en": "More than one player is called '{player}'. Pick the one you mean.",
        "es": "Hay más de un jugador llamado '{player}'. Elige el que quieres.",
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

    # -- status_label: shared by resolve_player and get_player_summary ------
    # Closed 5-value vocabulary. The renderer never sees the raw single-char
    # status code ("a"/"d"/"i"/"s"/"u") -- fpl_query_tools._STATUS_LABELS
    # already turns it into this English word before the tool output reaches
    # the renderer, so translation keys off the English value itself (see
    # renderer._localized_status_label). An adjective describing the player,
    # not a cross-referenced identifier -- translates like difficulty_label.
    "status_label.available": {"en": "Available", "es": "Disponible"},
    "status_label.doubtful": {"en": "Doubtful", "es": "Dudoso"},
    "status_label.injured": {"en": "Injured", "es": "Lesionado"},
    "status_label.suspended": {"en": "Suspended", "es": "Suspendido"},
    "status_label.unavailable": {"en": "Unavailable", "es": "No disponible"},
    # i151: the two extra codes find_players._STATUS_MAP can produce.
    "status_label.not_in_squad": {"en": "Not in squad", "es": "Fuera de la plantilla"},
    "status_label.unknown": {"en": "Unknown", "es": "Desconocido"},

    # -- resolve_player -------------------------------------------------------
    "resolve_player.summary_named": {
        "en": "{web_name} ({name}) plays for {team} ({team_short}) as a {position}. Status: {status_lbl}.",
        "es": "{web_name} ({name}) juega en {team} ({team_short}) como {position}. Estado: {status_lbl}.",
    },
    "resolve_player.summary_unnamed": {
        "en": "{web_name} plays for {team} ({team_short}) as a {position}. Status: {status_lbl}.",
        "es": "{web_name} juega en {team} ({team_short}) como {position}. Estado: {status_lbl}.",
    },
    "resolve_player.resolved_via_suffix": {
        "en": " [Resolved via: {via}]",
        "es": " [Resuelto vía: {via}]",
    },
    "resolve_player.ambiguous": {
        "en": (
            "Multiple players share the name '{query}'. "
            "Please use a full name or player ID to disambiguate "
            "(e.g. 'Who is Adam Johnson?' or 'Who is player 6?')."
        ),
        "es": (
            "Varios jugadores comparten el nombre '{query}'. "
            "Usa el nombre completo o el ID del jugador para desambiguar "
            "(por ejemplo, '¿Quién es Adam Johnson?' o '¿Quién es el jugador 6?')."
        ),
    },
    "resolve_player.not_found": {
        "en": "No player found matching '{query}'. Check the spelling or try a full name / player ID.",
        "es": "No encontré ningún jugador que coincida con '{query}'. Revisa la ortografía o prueba con el nombre completo o el ID del jugador.",
    },
    "resolve_player.error_fallback": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },

    # -- get_player_summary -----------------------------------------------
    "player_summary.line": {
        "en": "{display} | {team} ({team_short}) | {position} | £{cost_m}m | {ownership}% ownership | Status: {status_lbl}.",
        "es": "{display} | {team} ({team_short}) | {position} | £{cost_m}m | {ownership}% de propiedad | Estado: {status_lbl}.",
    },
    "player_summary.extra_total_pts": {
        "en": "Total pts: {total_pts}",
        "es": "Pts totales: {total_pts}",
    },
    "player_summary.extra_form": {
        "en": "Form: {form_val}",
        "es": "Forma: {form_val}",
    },
    "player_summary.extra_mins": {
        "en": "Mins: {minutes}",
        "es": "Min: {minutes}",
    },
    "player_summary.ambiguous": {
        "en": "Multiple players share the name '{query}'. Please use a full name or player ID to disambiguate.",
        "es": "Varios jugadores comparten el nombre '{query}'. Usa el nombre completo o el ID del jugador para desambiguar.",
    },
    "player_summary.not_found_fallback": {
        "en": "No player found matching '{query}'. Check the spelling or try a full name / player ID.",
        "es": "No encontré ningún jugador que coincida con '{query}'. Revisa la ortografía o prueba con el nombre completo o el ID del jugador.",
    },
    "player_summary.error_fallback": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },

    # -- get_injury_list -----------------------------------------------------
    # "other" groups both suspended ("s") and unavailable ("u") players under
    # one composite header -- see injury_list.py's bucketing -- so this is 3
    # header phrases, not 5 status values.
    "injury_list.none": {
        "en": "No injury concerns in the current bootstrap.",
        "es": "No hay problemas de lesiones en los datos actuales.",
    },
    "injury_list.injured_header": {
        "en": "Injured: {names}",
        "es": "Lesionados: {names}",
    },
    "injury_list.doubtful_header": {
        "en": "Doubtful: {names}",
        "es": "Dudosos: {names}",
    },
    "injury_list.suspended_header": {
        "en": "Suspended/unavailable: {names}",
        "es": "Suspendidos/no disponibles: {names}",
    },
    "injury_list.error_fallback": {
        "en": "An unexpected injury list error occurred.",
        "es": "Ocurrió un error inesperado al obtener la lista de lesiones.",
    },

    # -- get_captain_score ----------------------------------------------------
    # The result line itself ("{web_name} ({team_short}) — {tier_label}
    # [{score}].{reasons_clause}") carries no literal English words once
    # tier_label and reasons_clause are localized elsewhere -- only the
    # status branches below are this renderer's own prose.
    "captain_score.ambiguous": {
        "en": "Multiple players share the name '{query}'. Please use a full name or player ID to disambiguate.",
        "es": "Varios jugadores comparten el nombre '{query}'. Usa el nombre completo o el ID del jugador para desambiguar.",
    },
    "captain_score.not_found_fallback": {
        "en": "No player found matching '{query}'. Check the spelling or try a full name / player ID.",
        "es": "No encontré ningún jugador que coincida con '{query}'. Revisa la ortografía o prueba con el nombre completo o el ID del jugador.",
    },
    "captain_score.error_fallback": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },

    # -- rank_captain_candidates ----------------------------------------------
    # Same story as captain_score: each ranked line is pure interpolation
    # once tier_short/set_piece_label/reasons are localized elsewhere.
    "rank_captain.none": {
        "en": "No captain candidates could be scored.",
        "es": "No se pudo puntuar a ningún candidato a capitán.",
    },
    "rank_captain.error_fallback": {
        "en": "Could not rank captain candidates.",
        "es": "No se pudo clasificar a los candidatos a capitán.",
    },

    # -- tier: shared by get_captain_score (full) and rank_captain_candidates
    # (short bracket code), Phase 2i.  Adjectives describing a captaincy
    # pick, not cross-referenced identifiers -- translate like tier_label.
    "tier_label.safe": {"en": "Safe", "es": "Segura"},
    "tier_label.upside": {"en": "Upside", "es": "Con potencial"},
    "tier_label.differential": {"en": "Differential", "es": "Diferencial"},
    "tier_label.avoid": {"en": "Avoid", "es": "Evitar"},
    "tier_label.low_confidence": {"en": "Low-confidence", "es": "Baja confianza"},

    # Short bracket codes, e.g. "[safe]" / "[up]". Must stay compact -- a
    # Spanish code longer than the English one breaks the ranked-line
    # format. "pot" (potencial) is one character longer than "up"; every
    # other pair is equal length or shorter -- "baj" is a truncated
    # abbreviation of "baja" (confianza), not the full word, chosen
    # specifically to match "low"'s length. See the F2 report for the
    # per-entry reasoning.
    "tier_short.safe": {"en": "safe", "es": "seg"},
    "tier_short.upside": {"en": "up", "es": "pot"},
    "tier_short.differential": {"en": "diff", "es": "dif"},
    "tier_short.avoid": {"en": "avoid", "es": "evit"},
    "tier_short.low_confidence": {"en": "low", "es": "baj"},

    # -- set-piece labels: the inline "· {clause}" suffix in
    # rank_captain_candidates (_set_piece_clause/_set_piece_suffix).  Despite
    # the "short" naming of the sibling _SET_PIECE_SHORT map, that map is
    # dead code in renderer.py -- the live suffix always uses the full label
    # (see the F2 report) -- so these are the only set-piece strings that
    # actually render.
    "set_piece_label.penalty_taker_1": {"en": "penalty taker", "es": "pateador de penales"},
    "set_piece_label.penalty_taker_2": {"en": "2nd penalty taker", "es": "2do pateador de penales"},
    "set_piece_label.freekick_taker_1": {"en": "free-kick taker", "es": "pateador de tiros libres"},
    "set_piece_label.freekick_taker_2": {"en": "2nd free-kick taker", "es": "2do pateador de tiros libres"},

    # -- captain reasons: explainer.py's 15 fixed reason phrases (12 append
    # call sites -- the role-signal site alone yields 4 of the 15 via
    # _ROLE_REASON). Literal constants, not free prose, so they belong in
    # the catalogue exactly like an enum. explain_captain()/
    # explain_captain_compact() default locale to "en", not DEFAULT_LOCALE
    # -- comparison.py and transfer_advisor.py call these without a locale
    # argument and depend on English output for their own (tier-2b,
    # out-of-scope) recommendation text; only the two F2 renderer call
    # sites pass locale explicitly.
    "captain_reason.penalty_taker": {"en": "Penalty taker", "es": "Pateador de penales"},
    "captain_reason.penalty_taker_2nd": {"en": "2nd penalty taker", "es": "2do pateador de penales"},
    "captain_reason.freekick_taker": {"en": "Free-kick taker", "es": "Pateador de tiros libres"},
    "captain_reason.freekick_taker_2nd": {"en": "2nd free-kick taker", "es": "2do pateador de tiros libres"},
    "captain_reason.form_strong": {"en": "Strong recent form", "es": "Buena forma reciente"},
    "captain_reason.form_weak": {"en": "Weak recent form", "es": "Mala forma reciente"},
    "captain_reason.fixture_favorable": {"en": "Favorable fixture", "es": "Partido favorable"},
    "captain_reason.fixture_tough": {"en": "Tough fixture", "es": "Partido difícil"},
    "captain_reason.xgi_high": {"en": "High attacking involvement", "es": "Alta participación ofensiva"},
    "captain_reason.xgi_low": {"en": "Weak attacking process", "es": "Baja participación ofensiva"},
    "captain_reason.minutes_secure": {"en": "Secure minutes", "es": "Minutos asegurados"},
    "captain_reason.minutes_rotation_risk": {"en": "Rotation risk lowers confidence", "es": "El riesgo de rotación baja la confianza"},
    "captain_reason.minutes_significant_risk": {"en": "Significant minutes risk", "es": "Riesgo significativo de minutos"},
    "captain_reason.tier_differential": {"en": "High-upside differential profile", "es": "Perfil diferencial de alto potencial"},
    "captain_reason.tier_low_confidence": {"en": "Low-confidence captaincy profile", "es": "Perfil de capitanía de baja confianza"},

    "gw_report.no_team_connected": {
        "en": 'No team is connected. Connect your team from the Squad tab to get your gameweek review.',
        "es": 'No hay ningún equipo conectado. Conecta tu equipo desde la pestaña Plantilla para ver el resumen de tu jornada.',
    },
    "gw_report.team_not_found": {
        "en": "I couldn't find your connected FPL team. Check that the ID is correct.",
        "es": 'No encontré tu equipo FPL conectado. Revisa que el ID sea correcto.',
    },
    "gw_report.network_error": {
        "en": "I couldn't fetch your gameweek right now. Try again in a moment.",
        "es": 'No pude obtener tu jornada en este momento. Intenta de nuevo en un momento.',
    },
    "gw_report.invalid_gw": {
        "en": 'Gameweek must be between {min_gw} and {max_gw}.',
        "es": 'La jornada debe estar entre {min_gw} y {max_gw}.',
    },
    "gw_report.gw_not_finished": {
        "en": "GW{gw} isn't closed yet, so there is no final review to show. Ask again once FPL closes it.",
        "es": 'La J{gw} aún no está cerrada, así que todavía no hay un resumen final. Vuelve a preguntar cuando FPL la cierre.',
    },
    "gw_report.no_finished_gw": {
        "en": 'No gameweek has been closed yet this season, so there is no review to show.',
        "es": 'Todavía no se ha cerrado ninguna jornada esta temporada, así que no hay resumen que mostrar.',
    },
    "gw_report.incomplete": {
        "en": "I don't have complete official data for GW{gw} yet, so I'd rather not show a partial review.",
        "es": 'Aún no tengo datos oficiales completos de la J{gw}, así que prefiero no mostrar un resumen parcial.',
    },
    "gw_report.header": {
        "en": '**Gameweek review (retrospective) — GW{gw}**{chip_clause}',
        "es": '**Resumen retrospectivo — J{gw}**{chip_clause}',
    },
    "gw_report.points_ok": {
        "en": "Points: **{gross}**, matching FPL's official total.{hit_clause}",
        "es": 'Puntos: **{gross}**, coinciden con el total oficial de FPL.{hit_clause}',
    },
    "gw_report.points_hit_clause": {
        "en": ' Transfer cost: −{cost}, net **{net}**.',
        "es": ' Coste de fichajes: −{cost}, neto **{net}**.',
    },
    "gw_report.points_mismatch": {
        "en": "Heads-up: my sum is {computed} but FPL's official figure is {official} (difference {diff}). Treat the numbers below as unreconciled.",
        "es": 'Ojo: mi suma es {computed} pero la cifra oficial de FPL es {official} (diferencia {diff}). Toma las cifras de abajo como no reconciliadas.',
    },
    "gw_report.points_unverified": {
        "en": "I couldn't check my sum ({computed}) against FPL's official figure, so treat it as unverified.",
        "es": 'No pude comprobar mi suma ({computed}) con la cifra oficial de FPL, así que tómala como no verificada.',
    },
    "gw_report.provisional_note": {
        "en": "_FPL hasn't finished checking this gameweek's data; points may still change._",
        "es": '_FPL aún no termina de verificar los datos de esta jornada; los puntos pueden cambiar._',
    },
    "gw_report.xi_header": {
        "en": '**Effective XI (after automatic substitutions):**',
        "es": '**Once efectivo (tras las autosustituciones):**',
    },
    "gw_report.bench_header": {
        "en": '**Bench:**',
        "es": '**Banca:**',
    },
    "gw_report.player_line": {
        "en": '- {name} ({team}, {pos}) · {points} pts · {minutes} min{tags}',
        "es": '- {name} ({team}, {pos}) · {points} pts · {minutes} min{tags}',
    },
    "gw_report.tag_captain": {
        "en": ' · (C ×{mult})',
        "es": ' · (C ×{mult})',
    },
    "gw_report.tag_vice": {
        "en": ' · (VC)',
        "es": ' · (VC)',
    },
    "gw_report.tag_sub_in": {
        "en": ' · came on as an automatic sub',
        "es": ' · entró por autosustitución',
    },
    "gw_report.tag_sub_out": {
        "en": ' · automatically substituted',
        "es": ' · sustituido automáticamente',
    },
    "gw_report.armband_moved": {
        "en": 'The armband passed to vice-captain {vice} because captain {captain} did not play.',
        "es": 'El brazalete pasó al vice-capitán {vice} porque el capitán {captain} no jugó.',
    },
    "gw_report.stories_header": {
        "en": '**What stood out:**',
        "es": '**Lo que destacó:**',
    },
    "gw_report.story.captain_top": {
        "en": 'Captain: {captain} scored {captain_points} pts (×{multiplier} = {contribution}), the highest of your effective XI{tied}.',
        "es": 'Capitán: {captain} sumó {captain_points} pts (×{multiplier} = {contribution}), el máximo de tu once efectivo{tied}.',
    },
    "gw_report.story.captain_top_tied": {
        "en": ' (level with {names})',
        "es": ' (igualado con {names})',
    },
    "gw_report.story.captain_gap": {
        "en": '{best} was the best of your XI ({best_points} pts); the armband went to {captain} ({captain_points} {unit}, ×{multiplier}).',
        "es": '{best} fue el mejor de tu once ({best_points} pts); el brazalete fue para {captain} ({captain_points} {unit}, ×{multiplier}).',
    },
    "gw_report.story.autosub": {
        "en": 'Automatic substitution: {player_in} came on for {player_out} and scored {points_in} pts ({reason}).',
        "es": 'Autosustitución: {player_in} entró por {player_out} y sumó {points_in} pts ({reason}).',
    },
    "gw_report.story.autosub_no_fixture": {
        "en": "{player_out}'s team had no fixture",
        "es": 'el equipo de {player_out} no tenía partido',
    },
    "gw_report.story.autosub_not_played": {
        "en": '{player_out} did not play',
        "es": '{player_out} no jugó',
    },
    "gw_report.story.bench_points": {
        "en": 'Bench: {bench_points} pts stayed on the bench; the highest was {best} with {best_points}.',
        "es": 'Banca: {bench_points} pts se quedaron en la banca; el mayor fue {best} con {best_points}.',
    },
    "gw_report.story.bench_boost": {
        "en": 'Bench Boost: your bench added {bench_points} pts; the highest was {best} with {best_points}.',
        "es": 'Bench Boost: tu banca aportó {bench_points} pts; el mayor fue {best} con {best_points}.',
    },
    "gw_report.story.no_add": {
        "en": '{player} played {minutes} min and scored {points} pts{comparison}.',
        "es": '{player} jugó {minutes} min y sumó {points} pts{comparison}.',
    },
    "gw_report.story.no_add_comparison": {
        "en": ' (in his previous {n} appearances he averaged {avg} pts per match; a historical comparison, not an expectation)',
        "es": ' (en sus {n} partidos previos con minutos promedió {avg} pts por partido; comparación histórica, no una expectativa)',
    },
    "gw_report.story.minutes_change": {
        "en": 'Minutes: {player} played {per_fixture} min this gameweek, against an average of {avg} min in his last {n} appearances with minutes.',
        "es": 'Minutos: {player} jugó {per_fixture} min en esta jornada, frente a una media de {avg} min en sus últimos {n} partidos con minutos.',
    },
    "gw_report.footer": {
        "en": 'Retrospective review from official FPL data; it is not a forecast.',
        "es": 'Resumen retrospectivo con datos oficiales de FPL; no es una predicción.',
    },
    "gcard.gw_report.title": {
        "en": 'GW{gw} · RETROSPECTIVE',
        "es": 'J{gw} · RETROSPECTIVA',
    },
    "gcard.gw_report.subtitle": {
        "en": 'Your picks and points that gameweek',
        "es": 'Tus fichajes y puntos de esa jornada',
    },
    "gcard.gw_report.hero_ok": {
        "en": 'official points',
        "es": 'puntos oficiales',
    },
    "gcard.gw_report.hero_unreconciled": {
        "en": 'points (unreconciled)',
        "es": 'puntos (sin reconciliar)',
    },
    "gcard.gw_report.col_player": {
        "en": 'Player',
        "es": 'Jugador',
    },
    "gcard.gw_report.col_role": {
        "en": 'Role',
        "es": 'Rol',
    },
    "gcard.gw_report.col_min": {
        "en": 'Min',
        "es": 'Min',
    },
    "gcard.gw_report.col_pts": {
        "en": 'Pts',
        "es": 'Pts',
    },
    "gcard.gw_report.role_xi": {
        "en": 'XI',
        "es": 'Once',
    },
    "gcard.gw_report.role_sub_in": {
        "en": 'Sub in',
        "es": 'Entra',
    },
    "gcard.gw_report.role_sub_out": {
        "en": 'Sub out',
        "es": 'Sale',
    },
    "gcard.gw_report.role_bench": {
        "en": 'Bench',
        "es": 'Banca',
    },
    "gcard.gw_report.pill_reconciled": {
        "en": 'Matches FPL',
        "es": 'Cuadra con FPL',
    },
    "gcard.gw_report.pill_unreconciled": {
        "en": "Doesn't match FPL",
        "es": 'No cuadra con FPL',
    },
    "gcard.gw_report.pill_provisional": {
        "en": 'Provisional data',
        "es": 'Datos provisionales',
    },
    "gcard.gw_report.pill_hit": {
        "en": 'Hit −{cost}',
        "es": 'Coste −{cost}',
    },

    # -- get_my_squad (i39) --------------------------------------------------
    # The connected user's own squad. "no_team_connected" is the overwhelming
    # common case for any turn without a linked team -- see get_my_squad.py's
    # module docstring for why the tool degrades here instead of raising.
    "my_squad.no_team_connected": {
        "en": "No team is connected. Connect your team from the Squad tab so I can evaluate it.",
        "es": "No hay ningún equipo conectado. Conecta tu equipo desde la pestaña Plantilla para que pueda evaluarlo.",
    },
    "my_squad.team_not_found": {
        "en": "I couldn't find an FPL team with ID {team_id}. Check that the ID is correct.",
        "es": "No encontré ningún equipo FPL con el ID {team_id}. Revisa que el ID sea correcto.",
    },
    "my_squad.network_error": {
        "en": "I couldn't fetch your squad right now. Try again in a moment.",
        "es": "No pude obtener tu plantilla en este momento. Intenta de nuevo en un momento.",
    },
    "my_squad.invalid_gw": {
        "en": "Gameweek must be between {min_gw} and {max_gw}.",
        "es": "La jornada debe estar entre {min_gw} y {max_gw}.",
    },
    "my_squad.header": {
        "en": "**Your squad — GW{gw}**{chip_clause}",
        "es": "**Tu equipo — GW{gw}**{chip_clause}",
    },
    "my_squad.gw_clamped_note": {
        "en": (
            "_(GW{requested_gw} picks aren't published yet — showing your "
            "most recently confirmed squad, GW{gw}.)_"
        ),
        "es": (
            "_(La alineación de la GW{requested_gw} aún no fue publicada — "
            "muestro tu equipo confirmado más reciente, GW{gw}.)_"
        ),
    },
    "my_squad.chip_clause": {
        "en": " (active chip: {chip_label})",
        "es": " (chip activo: {chip_label})",
    },
    "my_squad.starters_header": {"en": "Starting XI:", "es": "Titulares:"},
    "my_squad.bench_header": {"en": "Bench:", "es": "Banquillo:"},
    "my_squad.player_line": {
        "en": "  {name} ({team}, {pos}) £{cost}m | {status_lbl} | form {form}{captain_tag}",
        "es": "  {name} ({team}, {pos}) £{cost}m | {status_lbl} | forma {form}{captain_tag}",
    },
    "my_squad.summary_line": {
        "en": "GW{gw}: {gw_points}pts | Total: {total_points}pts | In the bank: £{bank}m",
        "es": "GW{gw}: {gw_points}pts | Total: {total_points}pts | En el banco: £{bank}m",
    },
    "my_squad.error_fallback": {
        "en": "An unexpected error occurred.",
        "es": "Ocurrió un error inesperado.",
    },
    # -- decision_router.py: "top goalscorer" of a PAST season (i82) -------
    "decision.past_season_goals": {
        "en": (
            "I don't have goals per gameweek for past seasons, but I can tell you who "
            "scored the most **points**. Would that help?"
        ),
        "es": (
            "No tengo goles por jornada de temporadas pasadas; sí puedo decirte quién "
            "hizo más **puntos**. ¿Te sirve?"
        ),
    },

    # B4: starting-slot changes and who was missing (get_position_changes).
    "renderer.position_changes.header": {"en": "{name} ({team}): where he was listed to start, latest {n} matches with a stored lineup:", "es": "{name} ({team}): d\u00f3nde figur\u00f3 como titular, \u00faltimos {n} partidos con alineaci\u00f3n guardada:"},
    "renderer.position_changes.gw": {"en": "GW{gw}", "es": "J{gw}"},
    "renderer.position_changes.home": {"en": "{opp} (H)", "es": "{opp} (L)"},
    "renderer.position_changes.away": {"en": "{opp} (A)", "es": "{opp} (V)"},
    "renderer.position_changes.started": {"en": "started: {role}", "es": "titular: {role}"},
    "renderer.position_changes.bench": {"en": "on the bench", "es": "en el banquillo"},
    "renderer.position_changes.not_listed": {"en": "not in the stored squad list", "es": "no figura en la convocatoria guardada"},
    "renderer.position_changes.provisional": {"en": " (provisional lineup)", "es": " (alineaci\u00f3n provisional)"},
    "renderer.position_changes.changed": {"en": "    started in a different slot than in his recent starts (before: {before})", "es": "    empez\u00f3 en otra casilla que en sus \u00faltimos partidos (antes: {before})"},
    "renderer.position_changes.changed_line_forward": {"en": "    same role, different line: further forward than in his recent starts", "es": "    mismo rol, otra línea: más adelantado que en sus últimos partidos"},
    "renderer.position_changes.changed_line_deeper": {"en": "    same role, different line: deeper than in his recent starts", "es": "    mismo rol, otra línea: más retrasado que en sus últimos partidos"},
    "renderer.position_changes.line_unknown": {"en": "    same role; the line cannot be compared with his recent starts (different or unknown formation)", "es": "    mismo rol; la línea no es comparable con sus últimos partidos (formación distinta o desconocida)"},
    "renderer.position_changes.assoc": {"en": "    coincided with the absence of {name} from the starting XI ({presence}{sidelined}){unmapped}", "es": "    coincidi\u00f3 con la ausencia de {name} en el once inicial ({presence}{sidelined}){unmapped}"},
    "renderer.position_changes.presence_bench": {"en": "on the bench", "es": "estaba en el banquillo"},
    "renderer.position_changes.presence_not_listed": {"en": "not in the stored squad list", "es": "no figuraba en la convocatoria guardada"},
    "renderer.position_changes.sidelined": {"en": "; on the provider's sidelined list that day", "es": "; figuraba en la lista de bajas del proveedor ese d\u00eda"},
    "renderer.position_changes.unmapped": {"en": " \u2014 the stored lineup is incomplete, so he may have started", "es": " \u2014 la alineaci\u00f3n guardada est\u00e1 incompleta, por lo que pudo ser titular"},
    "renderer.position_changes.hypothesis": {"en": "    Unproven: he took the position {name} usually holds ({role})", "es": "    Sin demostrar: ocup\u00f3 la posici\u00f3n habitual de {name} ({role})"},
    "renderer.position_changes.no_change": {"en": "  No change of starting slot against his recent starts.", "es": "  Sin cambio de casilla frente a sus \u00faltimos partidos."},
    "renderer.position_changes.focus": {"en": "  Without {name} in the starting XI ({k} matches): {without}. With him starting ({m} matches): {with_him}.", "es": "  Sin {name} en el once inicial ({k} partidos): {without}. Con \u00e9l de titular ({m} partidos): {with_him}."},
    "renderer.position_changes.focus_none": {"en": "no usual position yet", "es": "sin posici\u00f3n habitual todav\u00eda"},
    "renderer.position_changes.small_sample": {"en": "  Small sample: {n} matches with a stored lineup, so this is a first look, not a trend.", "es": "  Muestra peque\u00f1a: {n} partidos con alineaci\u00f3n guardada; es una primera lectura, no una tendencia."},
    "renderer.position_changes.small_focus": {"en": "  In the starting XI without {name}: {k}; with him: {m}. It takes at least {min} matches on each side to read a pattern.", "es": "  En el once inicial sin {name}: {k}; con \u00e9l: {m}. Hacen falta al menos {min} partidos de cada lado para leer un patr\u00f3n."},
    "renderer.position_changes.assoc_more": {"en": "    and {n} more teammates were also out of the starting XI", "es": "    y {n} compa\u00f1eros m\u00e1s tampoco estaban en el once inicial"},
    "renderer.position_changes.footer": {"en": "  The slot is the announced starting XI, not movement during the match.", "es": "  La casilla es la del once inicial anunciado, no un movimiento durante el partido."},
    "renderer.position_changes.provenance": {"en": "Source: licensed lineup data, built {built_at}.", "es": "Fuente: datos de alineaciones con licencia, construidos el {built_at}."},
    "renderer.position_changes.missing": {"en": "There is no licensed lineup data for this question yet.", "es": "Todav\u00eda no hay datos de alineaciones con licencia para esta pregunta."},
    "renderer.position_changes.not_a_teammate": {"en": "{query} is not a teammate of {name}, so there is nothing to compare.", "es": "{query} no es compa\u00f1ero de equipo de {name}, por lo que no hay nada que comparar."},
    "renderer.position_changes.ambiguous": {"en": "More than one player matches '{query}'. Which one do you mean?", "es": "Hay m\u00e1s de un jugador que coincide con '{query}'. \u00bfA cu\u00e1l te refieres?"},
    "renderer.position_changes.not_found": {"en": "I could not find a player called '{query}'.", "es": "No encontr\u00e9 a ning\u00fan jugador llamado '{query}'."},

    # B4: get_position_changes card.
    "gcard.position_changes.title": {"en": "{name} \u00b7 starting slot", "es": "{name} \u00b7 casilla inicial"},
    "gcard.position_changes.subtitle": {"en": "Announced starting XI, not movement during the match", "es": "Once inicial anunciado, no un movimiento durante el partido"},
    # --- S5-B fixture outlook / fixture context (run verdicts, short-horizon read, phrases) ---
    "fxo.gw": {"en": "GW{n}", "es": "J{n}"},
    "fxo.no_series": {"en": "No fixtures in the horizon.", "es": "Sin fixtures en el horizonte."},
    "fxo.no_runs": {"en": "No clear runs in the fixture list over the horizon.", "es": "Calendario sin rachas claras en el horizonte."},
    "fxo.verdict.attack_good": {"en": "Good attacking run: {n} GWs of easy fixtures ({span}).", "es": "Buen tramo ofensivo: {n} jornadas de calendario asequible ({span})."},
    "fxo.verdict.attack_good_strong": {"en": "Good attacking run: {n} GWs of very easy fixtures ({span}).", "es": "Buen tramo ofensivo: {n} jornadas de calendario muy asequible ({span})."},
    "fxo.verdict.attack_bad": {"en": "Demanding attacking run: {n} tough GWs ({span}).", "es": "Tramo ofensivo exigente: {n} jornadas duras ({span})."},
    "fxo.verdict.attack_bad_strong": {"en": "Very demanding attacking run: {n} tough GWs ({span}).", "es": "Tramo ofensivo muy exigente: {n} jornadas duras ({span})."},
    "fxo.verdict.defence_good": {"en": "Good clean-sheet run: favourable fixtures ({span}).", "es": "Buen tramo para portería a cero: calendario favorable ({span})."},
    "fxo.verdict.defence_good_strong": {"en": "Good clean-sheet run: very favourable fixtures ({span}).", "es": "Buen tramo para portería a cero: calendario muy favorable ({span})."},
    "fxo.verdict.defence_bad": {"en": "Tricky run for keeping clean sheets ({span}).", "es": "Tramo complicado para mantener la portería a cero ({span})."},
    "fxo.verdict.defence_bad_strong": {"en": "Very tricky run for keeping clean sheets ({span}).", "es": "Tramo muy complicado para mantener la portería a cero ({span})."},
    "fxo.target_past": {"en": "GW{gw} has already been played \u2014 ask about the result, not the outlook.", "es": "La jornada {gw} ya se jug\u00f3 \u2014 pregunta por el resultado, no por el pron\u00f3stico."},
    "fxo.target_beyond": {"en": "No fixture data up to GW{gw} yet.", "es": "No hay datos de fixtures hasta la jornada {gw} todav\u00eda."},
    "fxo.band.attack.1": {"en": "very easy", "es": "muy asequible"},
    "fxo.band.attack.2": {"en": "easy", "es": "asequible"},
    "fxo.band.attack.3": {"en": "average", "es": "media"},
    "fxo.band.attack.4": {"en": "demanding", "es": "exigente"},
    "fxo.band.attack.5": {"en": "very demanding", "es": "muy exigente"},
    "fxo.band.defence.1": {"en": "very favourable", "es": "muy favorable"},
    "fxo.band.defence.2": {"en": "favourable", "es": "favorable"},
    "fxo.band.defence.3": {"en": "average", "es": "media"},
    "fxo.band.defence.4": {"en": "tricky", "es": "complicada"},
    "fxo.band.defence.5": {"en": "very tricky", "es": "muy complicada"},
    "fxo.axis.attack": {"en": "attacking", "es": "ofensiva"},
    "fxo.axis.defence": {"en": "for clean sheets", "es": "para portería a cero"},
    "fxo.rest": {"en": "{gw_tag}: {team} have a blank (no match).", "es": "{gw_tag}: {team} descansa (sin partido)."},
    "fxo.dgw": {"en": " (double gameweek)", "es": " (doble jornada)"},
    "fxo.venue_home": {"en": "at home to", "es": "en casa ante"},
    "fxo.venue_away": {"en": "away to", "es": "a domicilio ante"},
    "fxo.match": {
        "en": "{gw_tag}: {team} {venue} {opp} \u2014 {axis_label} difficulty {band}/5 ({qualifier})",
        "es": "{gw_tag}: {team} {venue} {opp} \u2014 dificultad {axis_label} {band}/5 ({qualifier})",
    },
    "fxo.edge_team": {"en": "edge {name}", "es": "ventaja {name}"},
    "fxo.edge_even": {"en": "evenly matched", "es": "fuerzas parejas"},
    "fxo.strength": {
        "en": "; overall strength {team} {ours}/5 {ours_venue} vs {opp} {theirs}/5 {theirs_venue} ({edge})",
        "es": "; fuerza global {team} {ours}/5 {ours_venue} vs {opp} {theirs}/5 {theirs_venue} ({edge})",
    },
    "fxo.at_home": {"en": "at home", "es": "en casa"},
    "fxo.away": {"en": "away", "es": "fuera"},
    "fxo.ctx.no_runs": {"en": "no marked runs in the fixtures", "es": "calendario sin rachas marcadas"},
    "fxo.ctx.attack_good": {"en": "favourable attacking fixtures ({span})", "es": "calendario ofensivo favorable ({span})"},
    "fxo.ctx.attack_bad": {"en": "demanding attacking fixtures ({span})", "es": "calendario ofensivo exigente ({span})"},
    "fxo.ctx.defmid_good": {"en": "favourable defensive fixtures ({span})", "es": "calendario defensivo favorable ({span})"},
    "fxo.ctx.defmid_bad": {"en": "demanding defensive fixtures ({span})", "es": "calendario defensivo exigente ({span})"},
    "fxo.ctx.cs_good": {"en": "good fixtures for clean sheets ({span})", "es": "buen calendario para portería a cero ({span})"},
    "fxo.ctx.cs_bad": {"en": "tough fixtures for clean sheets ({span})", "es": "calendario difícil para portería a cero ({span})"},
    "fxo.tiebreak": {"en": "Too close to call; on fixtures \u2014 {parts}.", "es": "Muy parejos; por calendario \u2014 {parts}."},
    "gcard.position_changes.hero": {"en": "slot changes", "es": "cambios de casilla"},
    "gcard.position_changes.col_gw": {"en": "GW", "es": "J"},
    "gcard.position_changes.col_opponent": {"en": "Opponent", "es": "Rival"},
    "gcard.position_changes.col_slot": {"en": "Started", "es": "Casilla"},
    "gcard.position_changes.col_note": {"en": "Note", "es": "Nota"},
    "gcard.position_changes.pill_small": {"en": "Only {n} matches with a lineup", "es": "Solo {n} partidos con alineaci\u00f3n"},
    "gcard.position_changes.pill_small_one": {"en": "Only 1 match with a lineup", "es": "Solo 1 partido con alineaci\u00f3n"},
    "gcard.position_changes.pill_without_one": {"en": "Only 1 match without {name}", "es": "Solo 1 partido sin {name}"},
    "gcard.position_changes.pill_with_one": {"en": "Only 1 match with {name}", "es": "Solo 1 partido con {name}"},
    "gcard.position_changes.pill_without": {"en": "Only {k} matches without {name}", "es": "Solo {k} partidos sin {name}"},
    "gcard.position_changes.pill_with": {"en": "Only {m} matches with {name}", "es": "Solo {m} partidos con {name}"},
    "gcard.position_changes.note_assoc_more": {"en": "and {n} more", "es": "y {n} m\u00e1s"},
    "gcard.position_changes.pill_provisional": {"en": "Provisional lineup", "es": "Alineaci\u00f3n provisional"},
    "gcard.position_changes.pill_focus": {"en": "Without {name}: {role}", "es": "Sin {name}: {role}"},
    "gcard.position_changes.note_changed": {"en": "Started in a different slot (before: {before})", "es": "Empez\u00f3 en otra casilla (antes: {before})"},
    "gcard.position_changes.note_line_forward": {"en": "Same role, different line: further forward", "es": "Mismo rol, otra línea: más adelantado"},
    "gcard.position_changes.note_line_deeper": {"en": "Same role, different line: deeper", "es": "Mismo rol, otra línea: más retrasado"},
    "gcard.position_changes.note_line_unknown": {"en": "Same role; line not comparable", "es": "Mismo rol; línea no comparable"},
    "gcard.position_changes.note_assoc": {"en": "Coincided with the absence of {name}", "es": "Coincidi\u00f3 con la ausencia de {name}"},
    "gcard.position_changes.note_none": {"en": "-", "es": "-"},
    # --- S5-B atomic cards + tool errors ---
    "atomic.col_player": {"en": "Player", "es": "Jugador"},
    "atomic.col_team": {"en": "Team", "es": "Equipo"},
    "atomic.title_top": {"en": "TOP {n} \u00b7 {header}", "es": "TOP {n} \u00b7 {header}"},
    "atomic.title_lowest": {"en": "{n} WITH LOWEST \u00b7 {header}", "es": "{n} CON MENOR \u00b7 {header}"},
    "atomic.title_highest": {"en": "{n} WITH HIGHEST \u00b7 {header}", "es": "{n} CON MAYOR \u00b7 {header}"},
    "atomic.sub_position": {"en": "position: {pos}", "es": "posici\u00f3n: {pos}"},
    "atomic.sub_min_minutes": {"en": "min. minutes: {n}", "es": "min. minutos: {n}"},
    "tool_err.no_team_connected": {
        "en": "No team is connected. Connect your team from the Squad tab so I can assess it.",
        "es": "No hay ning\u00fan equipo conectado. Conecta tu equipo desde la pesta\u00f1a Plantilla para que pueda evaluarlo.",
    },
    "tool_err.invalid_gw": {"en": "gw must be between {lo} and {hi}.", "es": "gw debe estar entre {lo} y {hi}."},
    "tool_err.team_not_found": {
        "en": "I could not find an FPL team with ID {team_id}. Check that the ID is correct.",
        "es": "No encontr\u00e9 ning\u00fan equipo FPL con el ID {team_id}. Revisa que el ID sea correcto.",
    },
    "tool_err.squad_server": {
        "en": "I could not fetch your squad (FPL server error: {exc}).",
        "es": "No pude obtener tu plantilla (error del servidor de FPL: {exc}).",
    },
    "tool_err.squad_network": {
        "en": "I could not fetch your squad (network failure: {exc}).",
        "es": "No pude obtener tu plantilla (fallo de red: {exc}).",
    },
    "tool_err.squad_raised": {
        "en": "get_my_squad raised an unexpected error: {exc}",
        "es": "get_my_squad raised an unexpected error: {exc}",
    },
    "tool_err.results_missing_team": {"en": "The team name is missing.", "es": "Falta el nombre del equipo."},
    "tool_err.results_venue": {"en": "venue must be one of {venues}, not {venue!r}.", "es": "venue debe ser uno de {venues}, no {venue!r}."},
    "tool_err.results_last_n": {"en": "last_n must be an integer, not {last_n!r}.", "es": "last_n debe ser un entero, no {last_n!r}."},
    "tool_err.results_team_not_found": {
        "en": "I could not find a team matching '{team}'.",
        "es": "No encontr\u00e9 ning\u00fan equipo que coincida con '{team}'.",
    },
    "tool_err.live_prov_unverified": {
        "en": "Data: current season (live FPL; season could not be verified)",
        "es": "Datos: temporada en curso (FPL en vivo; temporada no verificable)",
    },
    "tool_err.live_prov_suffix": {"en": "{label} (live FPL)", "es": "{label} (FPL en vivo)"},
    # --- S5-B zonal (backend text of get_zonal_weakness / get_zonal_opportunity / player outlook) ---
    "zonal.side.left": {"en": "down the left", "es": "por la izquierda"},
    "zonal.side.right": {"en": "down the right", "es": "por la derecha"},
    "zonal.side.central": {"en": "through the middle", "es": "por el centro"},
    "zonal.depth.in-box": {"en": "inside the box", "es": "dentro del \u00e1rea"},
    "zonal.depth.edge-of-box": {"en": "on the edge of the box", "es": "en la frontal del \u00e1rea"},
    "zonal.label_clear.in-box": {"en": "Attack inside the box", "es": "Ataca dentro del \u00e1rea"},
    "zonal.label_clear.edge-of-box": {"en": "Attack the edge of the box", "es": "Ataca la frontal del \u00e1rea"},
    "zonal.label_marginal.in-box": {"en": "Slight edge inside the box", "es": "Ventaja leve dentro del \u00e1rea"},
    "zonal.label_marginal.edge-of-box": {"en": "Slight edge on the edge of the box", "es": "Ventaja leve en la frontal del \u00e1rea"},
    "zonal.label_none": {"en": "No clear edge", "es": "Sin ventaja clara"},
    "zonal.verdict_none": {
        "en": "{team} do not concede above the league average in any zone of the box.",
        "es": "{team} no concede por encima de la media de la liga en ninguna zona del \u00e1rea.",
    },
    "zonal.verdict_marginal": {
        "en": "{team} do not concede clearly above average in any zone \u2014 the most favourable read is {side} {depth} ({pct:+.0f}%), a slight edge.",
        "es": "{team} no concede claramente por encima de la media en ninguna zona \u2014 la lectura m\u00e1s favorable es {side} {depth} ({pct:+.0f}%), una ventaja leve.",
    },
    "zonal.verdict_clear": {
        "en": "Attack {team} {side} {depth} \u2014 they concede {pct:+.0f}% over an average side there.",
        "es": "Ataca a {team} {side} {depth} \u2014 concede un {pct:+.0f}% sobre un equipo medio ah\u00ed.",
    },
    "zonal.verdict_multi": {
        "en": "Attack {team} {parts} \u2014 they concede above the league average there.",
        "es": "Ataca a {team} {parts} \u2014 concede por encima de la media de la liga ah\u00ed.",
    },
    "zonal.and": {"en": " and ", "es": " y "},
    "zonal.prov_unknown": {
        "en": "\u26a0 The tactical store does not declare which season this data is from",
        "es": "\u26a0 El almac\u00e9n t\u00e1ctico no declara de qu\u00e9 temporada son estos datos",
    },
    "zonal.prov_unverified": {
        "en": "Data: {label} season (could not verify the current season)",
        "es": "Datos: temporada {label} (no se pudo verificar la temporada en curso)",
    },
    "zonal.prov_stale": {
        "en": "\u26a0 {label} data, not from the current season ({live})",
        "es": "\u26a0 Datos de {label}, no de la temporada en curso ({live})",
    },
    "zonal.prov_thin": {
        "en": "\u26a0 {label} data, only {n} {unit} of league data \u2014 short sample for a league-wide read",
        "es": "\u26a0 Datos de {label}, s\u00f3lo {n} {unit} de liga \u2014 muestra corta para una lectura de liga",
    },
    "zonal.gw_one": {"en": "GW", "es": "jornada"},
    "zonal.gw_many": {"en": "GWs", "es": "jornadas"},
    "zonal.prov_current": {"en": "Data: {label} season", "es": "Datos: temporada {label}"},
    "zonal.player_favorable": {
        "en": "{player} generates their xG right in zones where the opponent concedes above average \u2014 favourable matchup in {gws}.",
        "es": "{player} genera su xG justo en zonas donde el rival concede por encima de la media \u2014 cruce favorable en {gws}.",
    },
    "zonal.player_neutral": {
        "en": "No standout zonal matchup for {player} in the next {n} GWs.",
        "es": "Sin cruce zonal destacado para {player} en las pr\u00f3ximas {n} jornadas.",
    },
    "zonal.gw_short": {"en": "GW", "es": "J"},
    "zonal.snap_no_data": {
        "en": "No zonal data on the opponents in these fixtures, so the matchup cannot be assessed.",
        "es": "Sin datos zonales de los rivales de estos partidos, no se puede valorar el cruce.",
    },
    "zonal.snap_neutral": {
        "en": "No standout zonal matchup for {player} in the fixtures of the next 3 GWs.",
        "es": "Sin cruce zonal destacado para {player} en los partidos de las pr\u00f3ximas 3 jornadas.",
    },
    "zonal.club_note": {"en": "previously at {club}", "es": "antes en {club}"},
    "zonal.fixtures_empty": {
        "en": "{team} have no fixtures in the next {horizon} GWs: league-wide ranking.",
        "es": "{team} no tiene partidos en las pr\u00f3ximas {horizon} jornadas: ranking de toda la liga.",
    },
    "zonal.no_calendar": {
        "en": "No fixture calendar in context: league-wide ranking.",
        "es": "Sin calendario en el contexto: ranking de toda la liga.",
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
