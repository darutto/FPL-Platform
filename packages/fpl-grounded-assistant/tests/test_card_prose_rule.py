"""A ranking card's prose must not print the card's rows (card_prose_rule).

Base behaviour: nothing in code looked at the text; a numbered list of the card's rows
(«1. **De Cuyper** — Brighton, £5.5m: **76 puntos**») went out above the card. Every
test that asserts the fix fails on the base (no module, no trimming). Synthetic players
only; fake provider client; no network, no paid call.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from types import SimpleNamespace as NS

import pytest

from fpl_grounded_assistant import card_prose_rule as rule
from fpl_grounded_assistant.card_prose_rule import REASON_ROWS_RESTATED, trim_card_restatement

RANKED = [
    {"web_name": "Alder", "metric_value": 76.0},
    {"web_name": "Birch", "metric_value": 70.0},
    {"web_name": "Van Cedar", "metric_value": 68.0},
    {"web_name": "Dogwood", "metric_value": 66.0},
    {"web_name": "Elm", "metric_value": 64.0},
]

LEO_SHAPE = (
    "Los mejores defensas de **menos de £6.0m por puntos totales** son:\n"
    "\n"
    "1. **Alder** — Brighton, £5.5m: **76 puntos**\n"
    "2. **Birch** — Brighton, £5.3m: **70 puntos**\n"
    "3. **Van Cedar** — Tottenham, £5.4m: **68 puntos**\n"
    "4. **Dogwood** — Arsenal, £5.9m: **66 puntos**\n"
    "\n"
    "Alder destaca porque su precio es bajo para lo que rinde."
)


def trim(text, ranked=RANKED, metric="total_points"):
    return trim_card_restatement(text, ranked, metric=metric)


# ---------------------------------------------------------------------------
# 1. What goes
# ---------------------------------------------------------------------------

def test_the_numbered_list_one_player_per_line_goes_with_its_intro_and_the_judgement_stays():
    out = trim(LEO_SHAPE)
    assert out.fired and out.dropped_lines == 5          # intro + 4 rows
    assert out.text == "Alder destaca porque su precio es bajo para lo que rinde."


@pytest.mark.parametrize("marker", ["- ", "* ", "• ", "1) "])
def test_bullets_and_other_markers(marker):
    text = "Así quedan:\n" + "\n".join(f"{marker}{r['web_name']}: {int(r['metric_value'])} puntos" for r in RANKED[:3])
    out = trim(text + "\n\nBuena zona de precios.")
    assert out.fired and out.text == "Buena zona de precios."


def test_markdown_table_rows_go_with_header_and_rule():
    text = (
        "| # | Jugador | Pts |\n|---|---|---|\n| 1 | Alder | 76 |\n| 2 | Birch | 70 |\n| 3 | Van Cedar | 68 |\n"
        "\nMucho nivel en Brighton."
    )
    out = trim(text)
    assert out.fired and out.text == "Mucho nivel en Brighton."


def test_consecutive_short_lines_without_markers():
    text = "Alder 76\nBirch 70\nVan Cedar 68\n\nEl resto queda lejos."
    out = trim(text)
    assert out.fired and out.text == "El resto queda lejos."


def test_a_sentence_with_three_players_each_beside_his_value_goes():
    out = trim("Alder (76), Birch (70) y Van Cedar (68) lideran.\n\nLo interesante es el precio.")
    assert out.fired and out.text == "Lo interesante es el precio."


@pytest.mark.parametrize("formats", [
    ("76", "70", "68"), ("76.0", "70.0", "68.0"), ("76 puntos", "70 pts", "68 puntos"), ("**76**", "**70**", "**68**"),
])
def test_values_in_the_cards_own_formats(formats):
    names = ["Alder", "Birch", "Van Cedar"]
    text = "\n".join(f"{i + 1}. {n} — {v}" for i, (n, v) in enumerate(zip(names, formats)))
    assert trim(text + "\n\nOk.").fired


def test_fractional_and_percent_values():
    ranked = [{"web_name": n, "metric_value": v} for n, v in (("Alder", 82.0), ("Birch", 77.5), ("Van Cedar", 70.25))]
    text = "- Alder: 82.0 %\n- Birch: 77.5 %\n- Van Cedar: 70.25 %\n\nBuena racha."
    out = trim(text, ranked, "selected_by_percent")
    assert out.fired and out.text == "Buena racha."


# ---------------------------------------------------------------------------
# 2. What stays
# ---------------------------------------------------------------------------

XG = [{"web_name": n, "metric_value": v} for n, v in (("Haaland", 9.1), ("Barry", 7.2), ("Isak", 6.9), ("Calvert", 6.1))]


def test_a_sentence_naming_players_without_values_is_untouched():
    text = (
        "El ranking actual de xG está dominado por delanteros: Haaland lidera con claridad, seguido por Barry "
        "e Isak. Calvert completa el top 4."
    )
    out = trim(text, XG, "expected_goals")
    assert not out.fired and out.text == text


def test_one_or_two_players_with_a_value_is_judgement_not_a_restatement():
    for text in (
        "Alder lidera con 76 puntos, y se nota.",
        "Alder (76) y Birch (70) se separan del resto.",
    ):
        assert not trim(text).fired


def test_two_list_lines_are_not_a_block():
    text = "Dos nombres:\n- Alder: 76 puntos\n- Birch: 70 puntos\n\nResto lejos."
    assert not trim(text).fired


def test_a_value_that_belongs_to_another_player_does_not_count():
    # three lines, each with a card name, but the numbers are other players' values or none of the card's
    text = "- Alder: 70 puntos\n- Birch: 68 puntos\n- Van Cedar: 76 puntos"
    assert not trim(text).fired


# -- a line that also carries judgement is never deleted ----------------------

COMMENT = "titular fijo y con calendario suave hasta la GW15"
CLUBS = ["Brighton", "BHA", "Tottenham", "TOT", "Arsenal", "ARS", "Man City", "MCI"]


def _rows(*lines):
    return "\n".join(lines)


def test_a_commented_line_stays_and_the_pure_rows_of_the_block_go():
    text = _rows(
        "Los mejores son:",
        "",
        f"1. **Alder** \u2014 76 puntos: {COMMENT}",
        "2. **Birch** \u2014 Brighton, \u00a35.3m: **70 puntos**",
        "3. **Van Cedar** \u2014 Tottenham, \u00a35.4m: **68 puntos**",
        "4. **Dogwood** \u2014 Arsenal, \u00a35.9m: **66 puntos**",
    )
    out = trim_card_restatement(text, RANKED, metric="total_points", extra_terms=CLUBS)
    assert out.fired and out.dropped_lines == 3
    assert out.text == f"Los mejores son:\n\n1. **Alder** \u2014 76 puntos: {COMMENT}"


def test_with_fewer_than_three_pure_rows_nothing_is_dropped():
    text = _rows(
        f"1. Alder: 76 puntos, {COMMENT}",
        f"2. Birch: 70 puntos, {COMMENT}",
        "3. Van Cedar: 68 puntos",
        "4. Dogwood: 66 puntos",
    )
    out = trim_card_restatement(text, RANKED, metric="total_points", extra_terms=CLUBS)
    assert not out.fired and out.text == text


def test_five_words_left_is_a_row_six_is_judgement():
    five = "uno mas bien muy flojo"
    six = "uno mas bien muy flojo ahora"
    base_rows = ("2. Birch: 70", "3. Van Cedar: 68", "4. Dogwood: 66")
    assert trim(_rows(f"1. Alder: 76 {five}", *base_rows)).text == ""
    assert trim(_rows(f"1. Alder: 76 {six}", *base_rows)).text == f"1. Alder: 76 {six}"


def test_clubs_positions_prices_values_and_units_do_not_count_as_judgement():
    text = _rows(
        "1. Alder (Man City, defensa, MCI) \u2014 \u00a35.5m \u00b7 76 puntos totales",
        "2. Birch (Brighton, DEF, BHA) \u2014 5.3m \u00b7 70 pts",
        "3. Van Cedar (Tottenham, delantero, TOT) \u2014 \u00a35.4m \u00b7 68 points",
    )
    out = trim_card_restatement(text, RANKED, metric="total_points", extra_terms=CLUBS)
    assert out.fired and out.text == ""


def test_a_table_with_a_comment_column_is_left_whole():
    text = _rows(
        "| # | Jugador | Pts | Nota |",
        "|---|---|---|---|",
        f"| 1 | Alder | 76 | {COMMENT} |",
        "| 2 | Birch | 70 | - |",
        "| 3 | Van Cedar | 68 | - |",
        "| 4 | Dogwood | 66 | - |",
    )
    out = trim(text)
    assert not out.fired and out.text == text


def test_a_sentence_with_a_real_clause_after_the_values_keeps_the_line():
    text = (
        "Alder (76), Birch (70) y Van Cedar (68) lideran, aunque solo el primero tiene un calendario "
        "suave hasta la GW15."
    )
    out = trim(text)
    assert not out.fired and out.text == text


def test_a_bare_sentence_of_three_values_still_goes():
    out = trim("Alder (76), Birch (70) y Van Cedar (68) lideran.\n\nLo interesante es el precio.")
    assert out.fired and out.text == "Lo interesante es el precio."


def test_leos_exact_shape_is_still_dropped_with_the_clubs_known():
    out = trim_card_restatement(LEO_SHAPE, RANKED, metric="total_points", extra_terms=CLUBS)
    assert out.fired and out.dropped_lines == 5
    assert out.text == "Alder destaca porque su precio es bajo para lo que rinde."


def test_the_card_name_and_the_name_the_prose_writes_may_differ():
    # The card shows FPL's web_name ("B.Fernandes", "Gibbs-White"); the model writes the full name.
    ranked = [{"web_name": n, "metric_value": v} for n, v in (
        ("Alder", 239.0), ("B.Fernandes", 235.0), ("Cedar", 209.0), ("Gibbs-White", 188.0))]
    text = (
        "**Alder** lidera con **239 puntos** esta temporada.\n\nLe siguen:\n\n"
        "2. Bruno Fernandes \u2014 235  \n3. Cedar \u2014 209  \n4. Gibbs White \u2014 188"
    )
    out = trim(text, ranked)
    assert out.fired
    assert out.text == "**Alder** lidera con **239 puntos** esta temporada."


def test_a_list_line_beside_a_confirmed_block_that_carries_a_card_value_joins_it():
    ranked = [{"web_name": n, "metric_value": v} for n, v in (("Alder", 76.0), ("Birch", 70.0), ("Cedar", 68.0), ("Dogwood", 66.0))]
    # the second line spells its player in a way no variant of the card name matches
    text = "Asi quedan:\n1. Alder: 76\n2. El joven Birchy: 70\n3. Cedar: 68\n4. Dogwood: 66\n\nBuen precio."
    out = trim(text, ranked)
    assert out.fired and out.text == "Buen precio."


def test_a_bare_surname_is_only_accepted_for_the_initial_form():
    ranked = [{"web_name": n, "metric_value": v} for n, v in (("Alder", 76.0), ("Birch", 70.0), ("Cedar", 68.0))]
    assert not trim("- Alder: 76\n- Birch: 70", ranked).fired     # two lines, no block
    initial = [{"web_name": n, "metric_value": v} for n, v in (("A.Smith", 76.0), ("Birch", 70.0), ("Cedar", 68.0))]
    assert trim("- Smith: 76\n- Birch: 70\n- Cedar: 68", initial).fired


def test_a_price_alone_is_not_the_metric_value():
    ranked = [{"web_name": n, "metric_value": v} for n, v in (("Alder", 5.5), ("Birch", 5.3), ("Van Cedar", 5.4))]
    text = "- Alder: £5.5m\n- Birch: £5.3m\n- Van Cedar: £5.4m"
    assert not trim(text, ranked, "total_points").fired      # a points ranking: those are prices
    assert trim(text, ranked, "now_cost").fired              # a price ranking: those ARE the values


def test_a_long_prose_paragraph_per_line_is_not_a_list():
    long_ = " Es un jugador muy regular que ha sumado muchísimo a lo largo de toda la temporada con apenas rotaciones"
    text = "\n".join(f"{r['web_name']} suma {int(r['metric_value'])} puntos y{long_}." for r in RANKED[:3])
    assert not trim(text).fired


def test_a_judgement_intro_without_a_colon_stays():
    text = "Mucho nivel en Brighton.\n- Alder: 76\n- Birch: 70\n- Van Cedar: 68"
    out = trim(text)
    assert out.fired and out.text == "Mucho nivel en Brighton."


def test_fewer_than_three_rows_never_fires():
    assert not trim("- Alder: 76\n- Birch: 70", RANKED[:2]).fired


def test_empty_and_plain_texts():
    assert not trim("").fired and not trim("Texto sin jugadores.").fired


# ---------------------------------------------------------------------------
# 3. The turn: /ask and /session, the audit, the fallback, never raising
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.dirname(_HERE)
_PKGS = os.path.dirname(_PKG)
for _path in [_PKG] + [
    os.path.join(_PKGS, p) for p in (
        "fpl-api-client", "fpl-data-core", "fpl-player-registry", "fpl-query-tools",
        "fpl-tool-contract", "fpl-tool-runner", "fpl-captain-engine",
    )
]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

import fpl_server  # noqa: E402
from fpl_grounded_assistant import harness as harness_mod  # noqa: E402
from fpl_grounded_assistant import orchestrator as orch_mod  # noqa: E402
from fpl_grounded_assistant.conversation_fixtures import STANDARD_BOOTSTRAP  # noqa: E402
from fpl_grounded_assistant.quota import reset_quota  # noqa: E402
from fpl_tool_runner import run_tool  # noqa: E402

Q = "mejores defensas por puntos"
CONCLUSIONS = [{
    "key": "gap",
    "params": {"leaders": ["Alder"], "metric": "total_points"},
    "evidence": {"lead_values": [76], "next_value": 70, "next_rank": 2},
}]


def _usage():
    return NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)


def _tool_use(*calls):
    blocks = [NS(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
    return NS(content=blocks, stop_reason="tool_use", usage=_usage())


def _text(text):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn", usage=_usage())


class _Client:
    def __init__(self, *responses, default):
        self.messages = self
        self.queue = list(responses)
        self.default = default

    def create(self, **_kw):
        return self.queue.pop(0) if self.queue else self.default


def _real_ranked():
    out = run_tool("rank_players_by_metric", {"metric": "total_points", "top_n": 5},
                   {**copy.deepcopy(STANDARD_BOOTSTRAP), "_rank_guard_internal": True})
    assert out["status"] == "ok"
    return out["ranked"]


def _list_text(ranked):
    rows = "\n".join(f"{i + 1}. **{r['web_name']}** — {r['team_short']}: **{int(r['metric_value'])} puntos**"
                     for i, r in enumerate(ranked[:4]))
    return f"Los mejores por puntos son:\n\n{rows}\n\n{ranked[0]['web_name']} lidera con claridad."


@pytest.fixture
def server(monkeypatch):
    fpl_server._init_bootstrap(STANDARD_BOOTSTRAP)
    fpl_server._sessions.clear()
    reset_quota()
    monkeypatch.setenv("FPL_ORCH_ENABLED", "1")
    monkeypatch.setenv("FPL_ORCH_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-never-used")
    monkeypatch.setenv("FPL_EVAL_DISABLED", "1")
    monkeypatch.delenv("FPL_JEV_MODE", raising=False)
    monkeypatch.delenv("FPL_ORCH_LOOP_ENABLED", raising=False)
    audit = []
    monkeypatch.setattr(fpl_server, "write_audit_entry", lambda entry: audit.append(entry))
    client = TestClient(fpl_server.app)
    client.audit = audit  # type: ignore[attr-defined]
    yield client
    fpl_server._sessions.clear()
    reset_quota()


@pytest.fixture
def model(monkeypatch):
    """The real orchestrator with a fake model: one ranking call, then ``state['text']`` as the answer."""
    state = {"text": "", "calls": [("rank_players_by_metric", {"metric": "total_points", "top_n": 5})]}
    real = orch_mod.ask_orchestrated

    def _wrapped(question, bootstrap, **kw):
        kw["client"] = _Client(_tool_use(*state["calls"]), default=_text(state["text"]))
        kw["provider"] = "anthropic"
        kw.pop("api_key", None)
        kw["_eval_client"] = None
        return real(question, bootstrap, **kw)

    monkeypatch.setattr(orch_mod, "ask_orchestrated", _wrapped)
    return state


def _post(server, route, body=None, headers=None):
    body = {"question": Q, **(body or {})}
    headers = {"X-User-Id": f"cp-{route}", **(headers or {})}
    if route == "ask":
        return server.post("/ask", json=body, headers=headers)
    sid = server.post("/session").json()["session_id"]
    return server.post(f"/session/{sid}/ask", json=body, headers=headers)


@pytest.mark.parametrize("route", ["ask", "session"])
def test_the_list_is_trimmed_on_both_routes_and_the_card_is_untouched(server, model, route):
    ranked = _real_ranked()
    model["text"] = _list_text(ranked)
    body = _post(server, route).json()
    assert body["final_text"] == f"{ranked[0]['web_name']} lidera con claridad."
    assert body["generic_card"] is not None and len(body["generic_card"]["rows"]) == len(ranked)
    assert body["outcome"] == "ok" and body["supported"] is True


def test_both_routes_serialize_the_trimmed_turn_the_same(server, model):
    model["text"] = _list_text(_real_ranked())
    a = _post(server, "ask").json()
    s = _post(server, "session").json()
    for key in ("final_text", "generic_card", "table_conclusions", "outcome", "intent", "supported", "review_passed"):
        assert a.get(key) == s.get(key), key


@pytest.mark.parametrize("route", ["ask", "session"])
def test_the_audit_line_keeps_the_original_and_an_enum_and_a_count(server, model, route):
    ranked = _real_ranked()
    model["text"] = _list_text(ranked)
    _post(server, route)
    entry = server.audit[-1]
    assert entry.card_prose_reason == REASON_ROWS_RESTATED
    assert entry.card_prose_dropped_lines == 5
    assert entry.card_prose_raw_answer_text == model["text"]


def test_a_clean_turn_has_no_card_prose_keys_in_its_audit_line(server, model, tmp_path):
    from fpl_grounded_assistant.audit import make_audit_entry

    ranked = _real_ranked()
    model["text"] = f"{ranked[0]['web_name']} lidera con claridad y el resto queda lejos."
    _post(server, "ask")
    entry = server.audit[-1]
    assert entry.card_prose_reason is None and entry.card_prose_raw_answer_text is None
    assert make_audit_entry(question="q", branch="b", outcome="ok").card_prose_reason is None


def test_nothing_remaining_falls_back_to_the_tables_conclusions(server, model, monkeypatch):
    ranked = _real_ranked()
    only_list = "\n".join(f"{i + 1}. {r['web_name']}: {int(r['metric_value'])} puntos" for i, r in enumerate(ranked[:4]))
    model["text"] = only_list
    monkeypatch.setattr(harness_mod, "_tool_table_conclusions", lambda *a, **k: CONCLUSIONS)
    for route in ("ask", "session"):
        body = _post(server, route).json()
        assert body["final_text"] == ""                       # the conclusions are what the user reads
        assert body["table_conclusions"] == CONCLUSIONS and body["generic_card"] is not None


def test_nothing_remaining_and_no_conclusions_keeps_the_original_text(server, model, monkeypatch):
    ranked = _real_ranked()
    only_list = "\n".join(f"{i + 1}. {r['web_name']}: {int(r['metric_value'])} puntos" for i, r in enumerate(ranked[:4]))
    model["text"] = only_list
    monkeypatch.setattr(harness_mod, "_tool_table_conclusions", lambda *a, **k: None)
    body = _post(server, "ask").json()
    assert body["final_text"] == only_list                    # never an empty bubble with nothing under it
    assert server.audit[-1].card_prose_reason is None


def test_a_rule_that_raises_sends_the_original_text(server, model, monkeypatch):
    ranked = _real_ranked()
    model["text"] = _list_text(ranked)

    def boom(*a, **k):
        raise RuntimeError("rule bug")

    monkeypatch.setattr(rule, "trim_card_restatement", boom)
    body = _post(server, "ask").json()
    assert body["final_text"] == model["text"]
    assert server.audit[-1].card_prose_reason is None


def test_a_turn_without_the_card_on_screen_is_never_touched(server, model):
    # Two tools in one turn: no single-tool card, so the rows are not on screen.
    ranked = _real_ranked()
    model["calls"] = [("rank_players_by_metric", {"metric": "total_points", "top_n": 5}), ("get_injury_list", {})]
    model["text"] = _list_text(ranked)
    body = _post(server, "ask").json()
    assert body["generic_card"] is None
    assert body["final_text"] == model["text"]


def test_another_tool_is_never_touched(server, model):
    model["calls"] = [("get_injury_list", {})]
    ranked = _real_ranked()
    model["text"] = _list_text(ranked)
    body = _post(server, "ask").json()
    assert body["final_text"] == model["text"]


def test_session_state_never_holds_the_answer_text(server, model):
    # The resolver's history is (question, intent) pairs, so a trimmed text cannot break the next turn.
    model["text"] = _list_text(_real_ranked())
    sid = server.post("/session").json()["session_id"]
    server.post(f"/session/{sid}/ask", json={"question": Q}, headers={"X-User-Id": "hist"})
    state = fpl_server._sessions[sid].session.state
    assert all(isinstance(h, tuple) and len(h) == 2 and all(isinstance(x, str) for x in h) for h in state.history)
    again = server.post(f"/session/{sid}/ask", json={"question": "¿y los porteros?"}, headers={"X-User-Id": "hist"})
    assert again.status_code == 200


# -- a heading that only names the dropped block goes with it -------------------

XA = [{"web_name": n, "metric_value": v} for n, v in (("Alder", 4.1), ("Birch", 3.6), ("Cedar", 3.2))]
XA_LIST = "1. Alder \u2014 4.1\n2. Birch \u2014 3.6\n3. Cedar \u2014 3.2"
XA_TITLE = "TOP 3 \u00b7 Asistencias esperadas (xA)"


@pytest.mark.parametrize("heading", [
    "### Top 10 por asistencias esperadas (xA)",          # the live case: this was all that stayed
    "## Ranking de xA",
    "**Top 10 por xA**",
    "**Top 10 por xA:**",
    "Top 3 por asistencias esperadas",                    # a plain line restating the card's title
    "### Los mejores jugadores de la temporada por asistencias esperadas",   # long, but only the title's words
])
def test_a_heading_over_a_fully_dropped_list_goes_and_nothing_remains(heading):
    out = trim_card_restatement(f"{heading}\n\n{XA_LIST}", XA, metric="expected_assists", card_title=XA_TITLE)
    assert out.fired and out.text == "" and out.dropped_lines == 4


def test_the_heading_and_the_intro_go_and_the_judgement_after_stays():
    text = f"### Top 3 por xA\n\nAs\u00ed quedan:\n\n{XA_LIST}\n\nAlder crea mucho m\u00e1s que el resto."
    out = trim_card_restatement(text, XA, metric="expected_assists", card_title=XA_TITLE)
    assert out.text == "Alder crea mucho m\u00e1s que el resto."


def test_a_heading_over_prose_that_stays_is_kept():
    text = f"### Lectura\n\nAlder crea mucho m\u00e1s que el resto.\n\n{XA_LIST}"
    out = trim_card_restatement(text, XA, metric="expected_assists", card_title=XA_TITLE)
    assert out.fired and out.text == "### Lectura\n\nAlder crea mucho m\u00e1s que el resto."


def test_a_heading_over_a_list_with_a_line_that_stays_is_kept():
    text = (
        "### Top 4\n\n1. Alder: 76 puntos\n2. Birch: 70 puntos\n3. Van Cedar: 68 puntos\n"
        "4. Dogwood: 66 puntos, titular fijo y con calendario suave hasta la GW15"
    )
    out = trim(text)
    assert out.fired and out.text.startswith("### Top 4\n\n4. Dogwood")


def test_a_heading_that_says_something_of_its_own_stays():
    heading = "### El que m\u00e1s crea juega en un equipo que apenas remata"
    out = trim_card_restatement(f"{heading}\n\n{XA_LIST}", XA, metric="expected_assists", card_title=XA_TITLE)
    assert out.fired and out.text == heading


def test_a_heading_over_a_dropped_sentence_goes_too_and_the_next_section_stays():
    text = "### Top 3\n\nAlder (4.1), Birch (3.6) y Cedar (3.2).\n\n### Lectura\n\nAlder crea mucho m\u00e1s que el resto."
    out = trim_card_restatement(text, XA, metric="expected_assists", card_title=XA_TITLE)
    assert out.text == "### Lectura\n\nAlder crea mucho m\u00e1s que el resto."


def test_a_title_alone_without_a_dropped_block_is_untouched():
    text = "### Top 3 por xA\n\nAlder crea mucho m\u00e1s que el resto."
    out = trim_card_restatement(text, XA, metric="expected_assists", card_title=XA_TITLE)
    assert not out.fired and out.text == text


@pytest.mark.parametrize("route", ["ask", "session"])
def test_only_a_heading_and_the_list_falls_back_to_the_conclusions(server, model, monkeypatch, route):
    ranked = _real_ranked()
    rows = "\n".join(f"{i + 1}. {r['web_name']}: {int(r['metric_value'])} puntos" for i, r in enumerate(ranked[:4]))
    model["text"] = f"### Top 5 por puntos\n\n{rows}"
    monkeypatch.setattr(harness_mod, "_tool_table_conclusions", lambda *a, **k: CONCLUSIONS)
    body = _post(server, route).json()
    assert body["final_text"] == "" and body["table_conclusions"] == CONCLUSIONS
