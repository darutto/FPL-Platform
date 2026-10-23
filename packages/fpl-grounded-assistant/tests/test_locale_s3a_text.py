"""i18n S3a -- tool-produced text follows the request's locale.

The tool handlers (comparison, transfer, chip, @injuries) build user-visible text
and take no locale argument, so the locale rides on the per-request bootstrap
copy under ``_locale`` (``locale_types.BOOTSTRAP_LOCALE_KEY``). These tests pin:

* the carrier (set on a COPY, only for non-default locales, never the shared dict);
* the comparison / transfer reasons and sentences in both locales, with es
  byte-for-byte what it was;
* the chip header and particular sentence twins (same keys as the es tables);
* the set-piece and venue words, the news passthrough, the injuries resource.

No network, no model call.
"""
from __future__ import annotations

import copy

import pytest

from conftest import BOOTSTRAP
from fpl_grounded_assistant import chip_two_part as chip
from fpl_grounded_assistant.comparison import _explain_comparison, compare_players
from fpl_grounded_assistant.locale_types import BOOTSTRAP_LOCALE_KEY, bootstrap_locale
from fpl_grounded_assistant.news_es import news_label
from fpl_grounded_assistant.scoring_shared import _set_piece_advantage_phrase, _venue_tag
from fpl_grounded_assistant.transfer_advisor import _build_transfer_reasons, get_transfer_advice


def _boot(locale: str | None) -> dict:
    boot = copy.deepcopy(BOOTSTRAP)
    if locale is not None:
        boot[BOOTSTRAP_LOCALE_KEY] = locale
    return boot


# ---------------------------------------------------------------------------
# The carrier
# ---------------------------------------------------------------------------

def test_bootstrap_locale_reads_en_and_defaults_to_es():
    assert bootstrap_locale({}) == "es"
    assert bootstrap_locale({BOOTSTRAP_LOCALE_KEY: "en"}) == "en"
    assert bootstrap_locale({BOOTSTRAP_LOCALE_KEY: "es"}) == "es"
    assert bootstrap_locale({BOOTSTRAP_LOCALE_KEY: "fr"}) == "es"
    assert bootstrap_locale(None) == "es"


def _ask_v2(question, locale, **kwargs):
    from fpl_grounded_assistant import harness

    shared = copy.deepcopy(BOOTSTRAP)
    result = harness.ask_v2(question, shared, locale=locale, **kwargs)
    assert BOOTSTRAP_LOCALE_KEY not in shared, "the shared server bootstrap must never be mutated"
    return result


@pytest.mark.parametrize(
    "locale,needle",
    [("es", "supera a Haaland"), ("en", "beats Haaland")],
)
def test_prompt_branch_reaches_the_tool_in_the_requests_locale(locale, needle):
    result = _ask_v2("/comparar Haaland vs Salah", locale)
    assert result["routing_trace"]["branch"] == "prompt"
    assert needle in result["answer_text"]
    assert needle in result["raw_output"]["recommendation"]


@pytest.mark.parametrize(
    "locale,needle",
    [("es", "supera a Haaland"), ("en", "beats Haaland")],
)
def test_orchestrated_branch_reaches_the_tool_in_the_requests_locale(monkeypatch, locale, needle):
    from types import SimpleNamespace as NS

    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")

    class _Client:
        def __init__(self) -> None:
            self.messages = self
            self.n = 0

        def create(self, **kwargs):
            self.n += 1
            usage = NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
            if self.n == 1:
                block = NS(type="tool_use", id="c1", name="compare_players",
                           input={"query_a": "Haaland", "query_b": "Salah"})
                return NS(content=[block], stop_reason="tool_use", usage=usage)
            return NS(content=[NS(type="text", text="done")], stop_reason="end_turn", usage=usage)

    result = _ask_v2(
        "which one is the better pick between the two forwards, think carefully",
        locale, orch_client=_Client(), orch_api_key="x",
    )
    assert result["routing_trace"]["branch"] == "orchestrator"
    assert needle in result["raw_output"]["recommendation"]


def test_resource_branch_status_words_follow_the_locale():
    es = _ask_v2("@lesionados", "es")
    en = _ask_v2("@lesionados", "en")
    assert es["routing_trace"]["branch"] == en["routing_trace"]["branch"] == "resource"
    es_rows, en_rows = es["resource_rows"]["rows"], en["resource_rows"]["rows"]
    assert es_rows and len(es_rows) == len(en_rows)
    assert [r["status_label"] for r in es_rows] != [r["status_label"] for r in en_rows]


# ---------------------------------------------------------------------------
# Comparison + transfer
# ---------------------------------------------------------------------------

def _scored(form=5.0, fdr=3, home=True, xgi=0.5, risk=0.0, role=None):
    return {
        "score_inputs": {
            "form": form, "fixture_difficulty": fdr, "effective_fdr": fdr,
            "is_home": home, "xgi_per_90": xgi, "minutes_risk": risk,
        },
        "role_signals": role or {},
    }


def test_explain_comparison_es_is_what_it_was():
    win = _scored(form=9.0, fdr=2, home=True, xgi=1.2, risk=0.0)
    lose = _scored(form=5.0, fdr=4, home=False, xgi=0.2, risk=60.0)
    assert _explain_comparison(win, lose) == [
        "mejor forma (9.0 vs 5.0)",
        "partido más fácil (FDR 2L vs 4V)",
        "más xGI por 90",
        "minutos más asegurados",
    ]
    assert _explain_comparison(win, lose, "es") == _explain_comparison(win, lose)


def test_explain_comparison_en():
    win = _scored(form=9.0, fdr=2, home=True, xgi=1.2, risk=0.0)
    lose = _scored(form=5.0, fdr=4, home=False, xgi=0.2, risk=60.0)
    assert _explain_comparison(win, lose, "en") == [
        "better form (9.0 vs 5.0)",
        "easier fixture (FDR 2H vs 4A)",
        "higher xGI per 90",
        "more secure minutes",
    ]


def test_transfer_reasons_share_the_same_phrases():
    inn = _scored(form=9.0, fdr=2, home=True, xgi=1.2, risk=0.0)
    out = _scored(form=5.0, fdr=4, home=False, xgi=0.2, risk=60.0)
    assert _build_transfer_reasons(inn, out, "en") == _explain_comparison(inn, out, "en")
    assert _build_transfer_reasons(inn, out) == _explain_comparison(inn, out)


def test_set_piece_phrase_follows_locale():
    better = {"role_bonus": 5.0, "set_piece_notes": ["penalty_taker_1"]}
    worse = {"role_bonus": 1.0, "set_piece_notes": ["freekick_taker_2"]}
    assert _set_piece_advantage_phrase(better, worse) == "ventaja a balón parado (penales vs 2.º en tiros libres)"
    assert _set_piece_advantage_phrase(better, worse, "en") == "set-piece advantage (penalties vs 2nd on free kicks)"
    assert _set_piece_advantage_phrase(better, {"role_bonus": 0.0}, "en") == "set-piece advantage (penalties)"
    assert _set_piece_advantage_phrase({"role_bonus": 1.0}, {"role_bonus": 0.0}, "en") == "set-piece advantage"


def test_venue_tag_follows_locale():
    assert (_venue_tag(True), _venue_tag(False), _venue_tag(None)) == ("L", "V", "")
    assert (_venue_tag(True, "en"), _venue_tag(False, "en"), _venue_tag(None, "en")) == ("H", "A", "")


def test_compare_players_recommendation_follows_the_bootstrap_locale():
    es = compare_players("Haaland", "Salah", _boot(None))
    en = compare_players("Haaland", "Salah", _boot("en"))
    assert es["recommendation"].startswith("Salah (62.0) supera a Haaland (56.0)")
    assert "diferencia moderada" in es["recommendation"] and "Ventajas:" in es["recommendation"]
    assert en["recommendation"].startswith("Salah (62.0) beats Haaland (56.0)")
    assert "moderate margin" in en["recommendation"] and "Advantages:" in en["recommendation"]
    assert en["comparison_reasons"] == ["better form (9.5 vs 8.0)"]
    # the numbers and the winner never depend on the locale
    for key in ("winner", "margin", "margin_label"):
        assert es[key] == en[key]


def test_get_transfer_advice_recommendation_follows_the_bootstrap_locale():
    es = get_transfer_advice("Haaland", "Salah", _boot(None))
    en = get_transfer_advice("Haaland", "Salah", _boot("en"))
    assert es["recommendation_text"].startswith("Recomendación: incorpora a Salah. Puntuación: 62 vs 56 de Haaland (+6.0).")
    assert "Ahorro neto:" in es["recommendation_text"]
    assert en["recommendation_text"].startswith("Recommendation: bring in Salah. Score: 62 vs 56 for Haaland (+6.0).")
    assert "Net saving:" in en["recommendation_text"]
    assert es["recommendation"] == en["recommendation"]


def test_tie_sentence_follows_locale():
    from fpl_grounded_assistant.comparison import _build_recommendation

    assert _build_recommendation("A", 50.0, "B", 50.0, None, 0.0, []) == "A (50.0) y B (50.0) empatan en puntuación."
    assert _build_recommendation("A", 50.0, "B", 50.0, None, 0.0, [], "en") == "A (50.0) and B (50.0) are level on score."


# ---------------------------------------------------------------------------
# Chip header + particular sentence
# ---------------------------------------------------------------------------

def test_chip_en_tables_have_the_same_keys_as_es():
    assert set(chip.GENERAL_VERDICT_LABEL_EN) == set(chip.GENERAL_VERDICT_LABEL)
    assert set(chip.PARTICULAR_PHRASE_EN) == set(chip.PARTICULAR_PHRASE)
    for key, phrase in chip.PARTICULAR_PHRASE_EN.items():
        assert phrase and phrase != chip.PARTICULAR_PHRASE[key], key
        assert ("{n}" in phrase) == ("{n}" in chip.PARTICULAR_PHRASE[key]), key


def _fit_output(verdict, missing=0, chip_name="bench_boost"):
    return {
        "status": "ok", "chip": chip_name, "recommendation": "conditions_favorable",
        "squad_source": "request",
        "squad_fit": {"verdict": verdict, "missing_count": missing},
        "signals": {
            "favoured_teams": [{"team": 1}, {"team": 2}, {"team": 3}],
            "favoured_players": [{"web_name": "Saka"}, {"web_name": "Palmer"}],
        },
    }


def test_chip_header_en_and_es():
    names = {1: "Arsenal", 2: "Chelsea", 3: "Spurs"}
    out = _fit_output("set")
    assert chip.general_header(out, names) == (
        "**Bench Boost — jornada favorable.** Grupo favorecido: Arsenal, Chelsea y Spurs (Saka, Palmer)."
    )
    assert chip.general_header(out, names, "en") == (
        "**Bench Boost — favourable gameweek.** Favoured group: Arsenal, Chelsea and Spurs (Saka, Palmer)."
    )


@pytest.mark.parametrize(
    "verdict,missing,es,en",
    [
        ("set", 0, "ya tienes el grupo favorecido", "you already have the favoured group"),
        ("needs_transfers", 1, "te falta 1 jugador del grupo favorecido para sacarle todo al chip",
         "you are 1 player short of the favoured group to get the most out of the chip"),
        ("needs_transfers", 3, "te faltan 3 jugadores del grupo favorecido para sacarle todo al chip",
         "you are 3 players short of the favoured group to get the most out of the chip"),
    ],
)
def test_chip_particular_phrase(verdict, missing, es, en):
    out = _fit_output(verdict, missing)
    assert chip.particular_phrase(out) == es
    assert chip.particular_phrase(out, "es") == es
    assert chip.particular_phrase(out, "en") == en


def test_chip_triple_captain_headers_and_invite():
    out = {
        "status": "ok", "chip": "triple_captain", "recommendation": "conditions_marginal",
        "squad_source": None,
        "signals": {"top_player": "Groß", "evaluated_player": "Salah"},
    }
    assert chip.general_header(out, {}) == (
        "**Triple Captain con Salah — jornada a medias.** Mejor candidato de la jornada: Groß."
    )
    assert chip.general_header(out, {}, "en") == (
        "**Triple Captain with Salah — mixed gameweek.** Best candidate of the gameweek: Groß."
    )
    assert chip.particular_phrase(out, "en") == chip.INVITE_TRIPLE_CAPTAIN_EN


def test_chip_compose_does_not_repeat_the_sentence_in_en():
    out = _fit_output("set")
    body = "You already have the favoured group, so go for it."
    composed = chip.compose_chip_answer(body, out, {1: "Arsenal"}, "en")
    assert composed.count("already have the favoured group") == 1


# ---------------------------------------------------------------------------
# News + injuries
# ---------------------------------------------------------------------------

def test_news_label_passes_english_through_untouched():
    news = "Knock - 75% chance of playing"
    assert news_label(news, "en") == news
    assert news_label(None, "en") == ""
    # es still translates (or passes through when it has no template)
    assert news_label(news) == news_label(news, "es")


def test_injuries_resource_status_label_follows_locale():
    from fpl_grounded_assistant.resource_registry import _resource_injuries

    def _rows(boot):
        result = _resource_injuries(boot)
        data = getattr(result, "data", result)
        return data["rows"] if isinstance(data, dict) else data.rows

    boot_es, boot_en = _boot(None), _boot("en")
    for boot in (boot_es, boot_en):
        for el in boot["elements"]:
            if el["id"] == 3:
                el["news"] = "Knock - 75% chance of playing"
    es_labels = {r["web_name"]: r["status_label"] for r in _rows(boot_es)}
    en_labels = {r["web_name"]: r["status_label"] for r in _rows(boot_en)}
    assert es_labels.keys() == en_labels.keys() and es_labels
    assert es_labels != en_labels, "status words must differ between locales"
    assert {r["web_name"]: r["news"] for r in _rows(boot_en)}["Saka"] == "Knock - 75% chance of playing"
