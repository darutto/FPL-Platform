"""The result contract of a ``query`` answer (query layer, PR 6).

``build`` / ``refused`` turn a run (or a refusal) into one tool output ``{status, query, query_audit}``:

* ``query`` -- the public block served on ``/ask`` and ``/session``. Rows (``table``) or sides
  (``comparison``) exist on ``complete`` only.
* ``query_audit`` -- enums only.

:func:`project` is the ONE reading of the block that every projection uses: outcome, supported,
review_passed, clarification flag and intent. :func:`final_text` is the whole answer text, written by code,
whose first line is the reading line. No model writes or rewords any of it.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from fpl_grounded_assistant import query_catalogue as cat
from fpl_grounded_assistant.query_engine import (COMPLETE, DATA_UNAVAILABLE, NEEDS_CLARIFICATION, UNSUPPORTED,
                                                 QueryResult)
from fpl_grounded_assistant.query_reading import PREFIX, SEPARATOR, WORDS, gameweeks_text, render_reading, value_text
from fpl_grounded_assistant.query_spec import PLAYER_PREDICATES, QuerySpec

STATES = (COMPLETE, NEEDS_CLARIFICATION, UNSUPPORTED, DATA_UNAVAILABLE)
INTENT_QUERY = "query"
BLOCK_VERSION = 1

#: User-facing words of the answer (the reading line's own words live in ``query_reading``).
TEXT: dict[str, dict[str, Any]] = {
    "es": {
        "player": "Jugador", "team": "Equipo", "club": "Club", "matches": "PJ", "minutes": "Min",
        "price": "Precio", "owned": "Propiedad", "empty": "Nadie cumple esas condiciones.",
        "side": "{label}: {value} ({n} partidos)", "side_metrics": "{label}: {metrics} ({n} partidos)",
        "per_match_hero": "{name} por partido", "total_hero": "{name} en total", "n_matches": "{n} partidos",
        "one_match": "1 partido", "venue_line": "Local {home} · visita {away}", "fdr_line": "FDR medio (hoy) {fdr}",
        "left_out": "{gw} fuera: jugó {minutes}′",
        "small": "Muestra pequeña: menos de 5 partidos en un grupo.",
        "overlap": "Los valores por partido de los dos grupos se solapan.",
        "apart": "Los valores por partido de los dos grupos no se solapan.",
        "before_join": "Fuera, de antes de que llegara al club: {gws}.",
        "tied": "Empatados sin mostrar: {n}.",
        "range": "Donde las dos medidas de xG no coinciden, muestro el rango.",
        "not_checked": "Sumas aún sin comprobar contra los totales de FPL.",
        "clarify": {
            "player_ambiguous": "¿A qué jugador te refieres con «{written}»?",
            "player_not_found": "No encuentro a «{written}».",
            "club_ambiguous": "¿Qué club es «{written}»?",
            "club_not_found": "No encuentro el club «{written}».",
            "player_not_at_club": "«{written}» no juega en ese club.",
            "missing_player_in_spec": "Nombraste a «{written}» y no lo he usado. ¿Cómo lo aplico?",
            "missing_club_in_spec": "Nombraste «{written}» y no lo he usado. ¿Cómo lo aplico?",
            "ambiguous_phrase": "¿Qué quieres decir exactamente?",
            "date": "¿De qué fecha hablas?",
            "invalid_spec": "No he entendido bien la consulta. ¿Puedes decirlo de otra forma?",
        },
        "unsupported": "Todavía no puedo calcular eso: {kinds}.",
        "ownership_then": "Solo tengo la propiedad de hoy.",
        "data": {
            "not_started": "Todavía no hay datos de {gws}.",
            "invariant_failed": "Los datos no cuadran con los totales de FPL, así que no muestro la tabla.",
            "too_few_matches": "Hay muy pocos partidos para comparar (mínimo 3 de cada lado).",
            "no_matches": "No hay partidos jugados en ese periodo.",
            "no_finished_gameweek": "Aún no hay jornadas terminadas.",
            "team_xg_unmeasured": "No se puede medir el xG de equipo en {gws}.",
            "double_gameweek_split": "No puedo separar los dos partidos de una jornada doble ({gws}).",
            "other": "No he podido leer los datos. Prueba de nuevo en un momento.",
        },
    },
    "en": {
        "player": "Player", "team": "Team", "club": "Club", "matches": "MP", "minutes": "Min",
        "price": "Price", "owned": "Owned", "empty": "Nobody meets those conditions.",
        "side": "{label}: {value} ({n} matches)", "side_metrics": "{label}: {metrics} ({n} matches)",
        "per_match_hero": "{name} per match", "total_hero": "{name} in total", "n_matches": "{n} matches",
        "one_match": "1 match", "venue_line": "Home {home} · away {away}", "fdr_line": "Mean FDR (today) {fdr}",
        "left_out": "{gw} left out: played {minutes}′",
        "small": "Small sample: fewer than 5 matches in one set.",
        "overlap": "The per-match values of the two sets overlap.",
        "apart": "The per-match values of the two sets do not overlap.",
        "before_join": "Left out, from before he joined the club: {gws}.",
        "tied": "Tied rows not shown: {n}.",
        "range": "Where the two xG measures differ, I show the range.",
        "not_checked": "Totals not yet checked against FPL's.",
        "clarify": {
            "player_ambiguous": "Which player do you mean by “{written}”?",
            "player_not_found": "I can't find “{written}”.",
            "club_ambiguous": "Which club is “{written}”?",
            "club_not_found": "I can't find the club “{written}”.",
            "player_not_at_club": "“{written}” does not play for that club.",
            "missing_player_in_spec": "You named “{written}” and I did not use it. How should I apply it?",
            "missing_club_in_spec": "You named “{written}” and I did not use it. How should I apply it?",
            "ambiguous_phrase": "What exactly do you mean?",
            "date": "Which date do you mean?",
            "invalid_spec": "I did not quite understand that. Could you put it another way?",
        },
        "unsupported": "I can't work that out yet: {kinds}.",
        "ownership_then": "I only have today's ownership.",
        "data": {
            "not_started": "There is no data for {gws} yet.",
            "invariant_failed": "The data does not add up to FPL's totals, so I am not showing the table.",
            "too_few_matches": "There are too few matches to compare (at least 3 on each side).",
            "no_matches": "No match has been played in that period.",
            "no_finished_gameweek": "No gameweek has finished yet.",
            "team_xg_unmeasured": "Team xG can't be measured for {gws}.",
            "double_gameweek_split": "I can't separate the two matches of a double gameweek ({gws}).",
            "other": "I couldn't read the data. Try again in a moment.",
        },
    },
}


# ------------------------------------------------------------------------------------------------ the projection

def project(block: Mapping[str, Any]) -> dict[str, Any]:
    """Outcome, supported, review_passed, clarification flag and intent of a block. Unknown states read as
    unsupported."""
    state = block.get("state")
    if state not in STATES:
        state = UNSUPPORTED
    return {
        "outcome": "ok" if state == COMPLETE else state,
        "supported": state in (COMPLETE, DATA_UNAVAILABLE),
        "review_passed": state != UNSUPPORTED,
        "clarification_asked": state == NEEDS_CLARIFICATION,
        "intent": INTENT_QUERY,
    }


# ---------------------------------------------------------------------------------------------- table and sides

def _column(header: str, align: str = "left", kind: str = "text") -> dict[str, str]:
    return {"header": header, "align": align, "kind": kind}


def _table(spec: QuerySpec, result: QueryResult, reading: Mapping[str, Any], lang: str) -> dict[str, Any]:
    words = TEXT[lang]
    team = spec.grain == "team"
    metric = next((p["label"] for p in reading["parts"] if p["kind"] == "metric"), spec.metric)
    filtered = {f.field for f in spec.filters}
    rate = spec.operator in ("per_match", "per_90") or result.min_minutes > 0
    columns = [_column(words["team" if team else "player"])]
    cells: list[Any] = [lambda r: r.name]
    if not team:
        columns.append(_column(words["club"], kind="badge"))
        cells.append(lambda r: r.club)
    if spec.second_metric is not None:
        for index, metric_id in enumerate((spec.metric, spec.second_metric)):
            name = cat.METRICS[metric_id].name[lang]
            columns.append(_column(name[:1].upper() + name[1:] if not name.startswith("x") else name,
                                   "right", "mono"))
            cells.append(lambda r, i=index: value_text(r.parts[i]))
    columns.append(_column(metric, "right", "mono"))
    cells.append(lambda r: value_text(r.value, r.value_range))
    if team:
        columns.append(_column(words["matches"], "right", "mono"))
        cells.append(lambda r: str(r.matches))
    else:
        if rate and spec.metric != "minutes":
            columns.append(_column(words["minutes"], "right", "mono"))
            cells.append(lambda r: str(r.minutes))
        if "price" in filtered or spec.operator == "per_million":
            columns.append(_column(words["price"], "right", "mono"))
            cells.append(lambda r: f"{r.price:.1f}")
        if "owned_now" in filtered:
            columns.append(_column(words["owned"], "right", "mono"))
            cells.append(lambda r: WORDS[lang]["percent"].format(n=f"{r.owned:.1f}"))
    return {"columns": columns, "rows": [[cell(row) for cell in cells] for row in result.rows]}


def _comparison(spec: QuerySpec, result: QueryResult, reading: Mapping[str, Any], lang: str) -> dict[str, Any]:
    comparison = result.comparison
    labels = {p["kind"]: p["label"] for p in reading["parts"]}
    per_match = spec.operator == "per_match"
    sides = []
    for kind, side in zip(("match_set", "compare_to"), comparison.sides):
        total_range = side.total_range
        mean_range = None if total_range is None else (total_range[0] / side.n, total_range[1] / side.n)
        total_text = value_text(side.total, total_range)
        per_match_text = value_text(side.per_match, mean_range)
        sides.append({
            "label": labels.get(kind, ""), "gameweeks": list(side.gameweeks), "n": side.n,
            "home": side.home, "away": side.away,
            "mean_fdr_text": None if side.mean_fdr is None else f"{side.mean_fdr:.2f}",
            "value_text": per_match_text if per_match else total_text,
            "total_text": total_text, "per_match_text": per_match_text,
            "per_match_values_text": [value_text(value, None if low == high else (low, high))
                                      for value, (low, high) in zip(side.per_match_values, side.per_match_bounds)]})
    return {"club": comparison.club, "metric_header": labels.get("metric", spec.metric), "sides": sides,
            "mixed": [{"gameweek": gw, "minutes": minutes} for gw, minutes in comparison.mixed],
            "before_join": list(comparison.before_join), "small_sample": comparison.small_sample,
            "ranges_overlap": comparison.ranges_overlap}


def _notes(result: QueryResult, comparison: Mapping[str, Any] | None, lang: str) -> list[str]:
    words = TEXT[lang]
    notes: list[str] = []
    if comparison is not None:
        notes.append(words["overlap" if comparison["ranges_overlap"] else "apart"])
        if comparison["small_sample"]:
            notes.append(words["small"])
        if comparison["before_join"]:
            notes.append(words["before_join"].format(gws=gameweeks_text(comparison["before_join"], lang)))
    if result.tied_omitted:
        notes.append(words["tied"].format(n=result.tied_omitted))
    if result.cross_check == "range":
        notes.append(words["range"])
    return notes


# --------------------------------------------------------------------------------------------- the card's blocks

def metric_block(name: str, comparison: Any, per_match: bool, lang: str, key: str,
                 per_match_shown: bool = True) -> dict[str, Any]:
    """One statistic of a comparison, labelled: per side its headline, total, per match and every match's value
    with its gameweek. *comparison* is the engine's."""
    words = TEXT[lang]
    sides = []
    for side in comparison.sides:
        total_range = side.total_range
        mean_range = None if total_range is None else (total_range[0] / side.n, total_range[1] / side.n)
        total_text = value_text(side.total, total_range)
        mean_text = value_text(side.per_match, mean_range) if per_match_shown else None
        sides.append({
            "value_text": mean_text if per_match else total_text, "total_text": total_text,
            "per_match_text": mean_text,
            "series": [{"label": gameweeks_text([gameweek], lang),
                        "value_text": value_text(value, None if low == high else (low, high))}
                       for (gameweek, _), value, (low, high)
                       in zip(side.matches, side.per_match_values, side.per_match_bounds)]})
    label = name if name.startswith("x") else name[:1].upper() + name[1:]
    hero = words["per_match_hero" if per_match else "total_hero"].format(name=name)
    return {"key": key, "label": label, "headline": "per_match" if per_match else "total",
            "hero_label": hero, "sides": sides}


def _card(spec: QuerySpec, result: QueryResult, block: dict[str, Any], lang: str) -> None:
    """What the comparison card draws, and the reading line said as a sentence: each set with its gameweeks and
    size, the matches left out with the minutes that left them out."""
    words, comparison, reading = TEXT[lang], block["comparison"], block["reading"]
    name = cat.METRICS[spec.metric].name[lang]
    if spec.second_metric is not None:
        name += cat.OPERATORS[spec.operator]["joiner"] + cat.METRICS[spec.second_metric].name[lang]
    comparison["metrics"] = [metric_block(name, result.comparison, spec.operator == "per_match", lang, spec.metric)]
    parts = [p for p in reading["parts"] if p["kind"] != "grain"]
    for kind, side in zip(("match_set", "compare_to"), comparison["sides"]):
        part = next(p for p in parts if p["kind"] == kind)
        gameweeks = gameweeks_text(side["gameweeks"], lang)
        size = words["one_match"] if side["n"] == 1 else words["n_matches"].format(n=side["n"])
        preds = [p["pred"] for p in part["value"]]
        title, _, tail = part["label"].rpartition(f": {gameweeks}")
        if preds in (["player_played_60"], ["player_absent"]):     # "(≥ 60′)" goes; the left-out line has minutes
            title = title.rsplit(" (", 1)[0]
            if preds == ["player_absent"]:                          # "Sin" alone would not say without whom
                subject = comparison["sides"][0].get("subject")
                if subject and subject not in title:
                    title = f"{title} {subject}"
            else:
                side["subject"] = title.split(" ", 1)[1]
        side["title"] = title + tail
        side["detail"] = f"{gameweeks} · {size}"
        venue = [words["venue_line"].format(home=side["home"], away=side["away"])]
        if side["mean_fdr_text"]:
            venue.append(words["fdr_line"].format(fdr=side["mean_fdr_text"]))
        side["venue_text"] = " · ".join(venue)
        part["label"] = f"{side['title']} ({gameweeks}, {size})"
    for side in comparison["sides"]:
        side.pop("subject", None)
    for part in parts:
        if part["kind"] == "mixed":
            part["label"] = SEPARATOR.join(
                words["left_out"].format(gw=gameweeks_text([m["gameweek"]], lang), minutes=m["minutes"])
                for m in comparison["mixed"])
    reading["parts"] = parts
    reading["text"] = SEPARATOR.join(p["label"] for p in parts)


# ------------------------------------------------------------------------------------------------------- chips

def _clarify_chips(spec: QuerySpec, result: QueryResult) -> list[dict[str, Any]]:
    """The engine's candidates as chips: each is the whole typed spec with the unclear name settled."""
    clarify = result.clarify or {}
    kind, written = clarify.get("kind"), clarify.get("written")
    chips = []
    for candidate in clarify.get("candidates") or ():
        raw = spec.to_dict()
        if kind == "player":                          # the id: the one spelling that cannot be ambiguous
            for side in ("match_set", "compare_to"):
                for pred in raw.get(side, []):
                    if pred["pred"] in PLAYER_PREDICATES and pred["value"] == written:
                        pred["value"] = str(candidate["id"])
            label = f"{candidate['web_name']} ({candidate['team_short']})"
        elif kind == "club":
            for item in raw["filters"]:
                if item["field"] == "club":
                    values = item["value"] if isinstance(item["value"], list) else [item["value"]]
                    values = [candidate["short_name"] if v == written else v for v in values]
                    item["value"] = values if isinstance(item["value"], list) else values[0]
            label = str(candidate["name"])
        elif kind == "player_club":
            raw["filters"] = [f for f in raw["filters"] if f["field"] != "club"] + [
                {"field": "club", "op": "eq", "value": candidate["club"]}]
            label = str(candidate["club"])
        else:
            continue
        chips.append({"label": label, "spec": raw})
    return chips


# ------------------------------------------------------------------------------------------------------ blocks

def _block(state: str, reason: str | None, lang: str, **extra: Any) -> dict[str, Any]:
    block = {"v": BLOCK_VERSION, "state": state, "reason": reason, "lang": lang, "spec": None, "reading": None,
             "table": None, "comparison": None, "chips": [], "notes": [], "footnote": None, "sum_check": None,
             "changed_parts": []}
    block.update(extra)
    return block


def _output(block: dict[str, Any], brake: str | None) -> dict[str, Any]:
    return {"status": "ok" if block["state"] == COMPLETE else block["state"], "query": block,
            "query_audit": {"state": block["state"], "reason": block["reason"], "brake": brake}}


def build(spec: QuerySpec, result: QueryResult, bootstrap: Mapping[str, Any], lang: str,
          chips: Iterable[Mapping[str, Any]] = (), brake: str | None = None,
          unused: Iterable[str] = ()) -> dict[str, Any]:
    """The tool output for a run (or a brake) of *spec*."""
    reading = render_reading(spec, lang, result, bootstrap)
    footnote = None
    if result.state == COMPLETE and result.sum_check == "not_checked":     # small print, not part of the reading
        footnote = TEXT[lang]["not_checked"]
        reading["parts"] = [p for p in reading["parts"] if p["value"] != "not_checked"]
        reading["text"] = SEPARATOR.join(p["label"] for p in reading["parts"])
    for kind in unused:                      # said, not braked: the answer below does not depend on it
        label = WORDS[lang]["unused"].format(name=WORDS[lang]["kinds"][kind])
        reading["parts"].append({"kind": "unused", "label": label, "value": kind, "editable": False,
                                 "alternatives": [], "braked": False})
        reading["text"] += SEPARATOR + label
    block = _block(result.state, result.reason, lang, spec=spec.to_dict(), reading=reading,
                   chips=[dict(c) for c in chips])
    if result.state == COMPLETE:
        if result.comparison is not None:
            block["comparison"] = _comparison(spec, result, reading, lang)
        else:
            block["table"] = _table(spec, result, reading, lang)
        block["notes"] = _notes(result, block["comparison"], lang)
        block["sum_check"] = result.sum_check
        block["footnote"] = footnote
        if result.comparison is not None:
            _card(spec, result, block, lang)
    elif result.state == NEEDS_CLARIFICATION and not block["chips"]:
        block["chips"] = _clarify_chips(spec, result)
    block["message"] = _message(block, result, lang)
    return _output(block, brake)


def refused(lang: str, state: str, reason: str, *, kinds: tuple[str, ...] = (), brake: str | None = None,
            detail: str | None = None) -> dict[str, Any]:
    """A refusal with no spec to show: there is nothing to read back, only what cannot be done."""
    block = _block(state, reason, lang)
    if kinds:
        names = ", ".join(WORDS[lang]["kinds"][k] for k in kinds)
        label = WORDS[lang]["unavailable"].format(names=names)
        block["reading"] = {"parts": [{"kind": "unsupported", "label": label, "value": list(kinds),
                                       "editable": False, "alternatives": [], "braked": True}],
                            "text": label, "lang": lang}
    block["message"] = _message(block, None, lang, kinds=kinds)
    out = _output(block, brake)
    if detail:
        out["query_audit"]["detail"] = detail
    return out


def _message(block: Mapping[str, Any], result: QueryResult | None, lang: str,
             kinds: tuple[str, ...] = ()) -> str | None:
    """The sentence under the reading line of a non-complete answer."""
    words = TEXT[lang]
    state, reason = block["state"], block["reason"]
    if state == COMPLETE:
        return None
    if state == NEEDS_CLARIFICATION:
        written = str(((result.clarify if result else None) or {}).get("written") or "")
        template = words["clarify"].get(reason) or words["clarify"].get(
            "date" if (result and (result.clarify or {}).get("kind") == "date") else "invalid_spec")
        return template.format(written=written)
    if state == UNSUPPORTED:
        listed = kinds or (result.unsupported if result else ())
        names = ", ".join(WORDS[lang]["kinds"].get(k, k) for k in listed)
        text = words["unsupported"].format(kinds=names)
        return f"{text} {words['ownership_then']}" if "ownership_then" in listed else text
    gameweeks = result.missing_gameweeks if result else ()
    template = words["data"].get(reason, words["data"]["other"])
    if "{gws}" in template and not gameweeks:
        template = words["data"]["other"]
    return template.format(gws=gameweeks_text(gameweeks, lang) if gameweeks else "")


# ---------------------------------------------------------------------------------------------------- the text

def final_text(block: Mapping[str, Any]) -> str:
    """The whole answer, for the text surface and any client that cannot draw the card."""
    lang = block["lang"]
    lines: list[str] = []
    if block["reading"] is not None:
        lines.append(PREFIX[lang] + block["reading"]["text"])
    if block["state"] != COMPLETE:
        lines.append(block["message"])
        return "\n".join(lines)
    table, comparison = block["table"], block["comparison"]
    if comparison is not None:
        metrics = comparison["metrics"]
        for index, s in enumerate(comparison["sides"]):
            if len(metrics) == 1:
                lines.append(TEXT[lang]["side"].format(label=s["label"], value=s["value_text"], n=s["n"]))
                continue
            said = SEPARATOR.join(f"{m['sides'][index]['value_text']} {m['hero_label']}" for m in metrics)
            lines.append(TEXT[lang]["side_metrics"].format(label=s["label"], metrics=said, n=s["n"]))
    elif not table["rows"]:
        lines.append(TEXT[lang]["empty"])
    else:
        headers = [c["header"] for c in table["columns"]]
        lines.append(" | ".join(headers))
        lines += [f"{i}. " + " | ".join(row) for i, row in enumerate(table["rows"], start=1)]
    lines += block["notes"] + ([block["footnote"]] if block.get("footnote") else [])
    return "\n".join(lines)
