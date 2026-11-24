"""What the plan_to_sign card says about its best option, and the chips for the others (PR 4 of 4).

Pure wording over the tool's own output: every number and every reason was decided in ``plan_to_sign``
(``tops_sold`` with its ``why``, ``sold``, ``trend_checks``, ``signals``); nothing here computes or guesses.

At most :data:`MAX_CONCLUSIONS` short lines, first rule wins:

1. the move choice gave no better plan (hits or free transfers, yet the best plan is one move);
2. why each top goes: the only way to fund the target (only when EVERY option sells that same player; when
   every option sells some top but not the same one, a single "every way ... sells a top player" line),
   FPL says he is out / the chance he plays, or the short recent-against-season comparison of a decline;
3. a sold player who is out or doubtful (a non-top);
4. a sold player with a hard run (3+ hard fixtures in the next 5);
5. a sold player with few starts this season (never "rotating": the figure is season-long).

One more line, from cached ownership numbers (``plan_eo``; never present without them): when the target is owned by
many near the user's rank (or in the top 10K) AND the option sells no one owned as much, "signing him covers you";
else when the plan sells a premium almost nobody near the user's rank owns and nobody else widely owned,
"selling him does not expose you". Both are checked on the hero option itself. It has a RESERVED slot (the others are cut to
:data:`MAX_CONCLUSIONS` - 1) and yields only to a sold player who is out or doubtful.

``focus`` (1-based, set when the user taps an option chip) picks which option is the hero; the others
become chips.
"""
from __future__ import annotations

from typing import Any

from .catalogue import t
from .locale_types import DEFAULT_LOCALE, Locale
from .plan_eo import SOLD_NO_EXPOSURE_PCT, TARGET_NEAR_COVER_PCT, TARGET_TOP_COVER_PCT

MAX_CONCLUSIONS: int = 3
#: Hard fixtures in the next five worth a line (same bar as the trend rule).
HARD_RUN_LINE: int = 3


def hero_index(raw_output: dict[str, Any]) -> int:
    """0-based index of the option the card is about."""
    options = raw_output.get("options") or []
    focus = raw_output.get("focus")
    if isinstance(focus, int) and not isinstance(focus, bool) and 1 <= focus <= len(options):
        return focus - 1
    return 0


def _num(value: float) -> str:
    return f"{value:.1f}" if value is not None else "?"


def _availability_line(option: dict[str, Any], sold: dict[str, Any], locale: Locale) -> str | None:
    transfer = next((tr for tr in option["transfers"] if tr["out"]["id"] == sold["id"]), None)
    if transfer is None or sold.get("availability") not in ("unavailable", "doubt"):
        return None
    chance = transfer["out"].get("chance_of_playing")
    if sold["availability"] == "doubt" and isinstance(chance, (int, float)) and not isinstance(chance, bool):
        return t("plan_to_sign.concl_doubt", locale, name=sold["web_name"], chance=int(chance))
    return t("plan_to_sign.concl_out", locale, name=sold["web_name"])


def _ref(raw_output: dict[str, Any], key: str) -> dict[str, Any]:
    return (raw_output.get("ownership") or {}).get(key) or {}


def _sold_ids(option: dict[str, Any]) -> list[int]:
    ids = [s["id"] for s in option.get("sold") or []]
    return ids or [tr["out"]["id"] for tr in option.get("transfers") or []]


def _sold_pcts(ref: dict[str, Any], option: dict[str, Any]) -> list[int | None]:
    return [(ref.get("sold") or {}).get(str(pid)) for pid in _sold_ids(option)]


def _net_cover(ref: dict[str, Any], option: dict[str, Any]) -> bool:
    """Signing the target covers the user in this reference only if NO player this option sells is owned as much
    as him or more (selling a 50 % player to buy a 30 % one does not cover). Unknown numbers: no claim."""
    target = ref.get("target")
    pcts = _sold_pcts(ref, option)
    return target is not None and bool(pcts) and all(isinstance(p, int) and p < target for p in pcts)


def _cover_line(raw_output: dict[str, Any], option: dict[str, Any], locale: Locale) -> str | None:
    """The target is widely owned by the managers near the user's rank (and/or the top 10K) and the option does not
    sell someone owned as much: signing him covers. Checked per option (the hero changes with ``focus``)."""
    name = (raw_output.get("target") or {}).get("web_name", "")
    near_ref, top_ref = _ref(raw_output, "near_rank_owned_pct"), _ref(raw_output, "top10k_owned_pct")
    near = near_ref.get("target") if _net_cover(near_ref, option) else None
    top = top_ref.get("target") if _net_cover(top_ref, option) else None
    if near is not None and near >= TARGET_NEAR_COVER_PCT:
        if top is not None and top >= 1:
            return t("plan_to_sign.concl_eo_cover", locale, name=name, near=near, top=top)
        return t("plan_to_sign.concl_eo_cover_near", locale, name=name, near=near)
    if top is not None and top >= TARGET_TOP_COVER_PCT:
        return t("plan_to_sign.concl_eo_cover_top", locale, name=name, top=top)
    return None


def _no_exposure_line(raw_output: dict[str, Any], option: dict[str, Any], locale: Locale) -> str | None:
    """A premium the option sells that almost nobody near the user's rank owns: selling him costs no cover.

    One line, naming the player (an option may sell several): the rarest premium sold, the lowest id on a tie.
    No line when any other player the option sells is widely owned near the user's rank (the plan as a whole then
    does expose) or when a sold player's number is unknown.
    """
    ref = _ref(raw_output, "near_rank_owned_pct")
    sold = ref.get("sold") or {}
    pcts = {pid: sold.get(str(pid)) for pid in _sold_ids(option)}
    if not pcts or any(not isinstance(p, int) for p in pcts.values()):
        return None
    rare = [(pcts[top["id"]], top["id"], top["web_name"]) for top in option.get("tops_sold") or []
            if pcts.get(top.get("id")) is not None and pcts[top["id"]] <= SOLD_NO_EXPOSURE_PCT]
    if not rare:
        return None
    pct, pid, name = min(rare)
    if any(p >= TARGET_NEAR_COVER_PCT for other, p in pcts.items() if other != pid):
        return None
    return t("plan_to_sign.concl_eo_no_exposure", locale, name=name)


#: The EO line kinds, tried in order: the first that applies is THE line (at most one per card).
_EO_LINES = (_cover_line, _no_exposure_line)


def _eo_line(raw_output: dict[str, Any], option: dict[str, Any], locale: Locale) -> str | None:
    if not raw_output.get("ownership"):
        return None
    for kind in _EO_LINES:
        line = kind(raw_output, option, locale)
        if line:
            return line
    return None


def plan_conclusions(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> list[str]:
    """The 0-3 lines about the hero option (already worded; dot decimals in both languages)."""
    options = raw_output.get("options") or []
    if not options:
        return []
    option = options[hero_index(raw_output)]
    target = (raw_output.get("target") or {}).get("web_name", "")
    lines: list[str] = []

    moves = raw_output.get("moves")
    if moves in ("hits", "free") and all(o.get("moves") == 1 for o in options):
        lines.append(t("plan_to_sign.concl_hits_no_better" if moves == "hits" else "plan_to_sign.concl_free_no_better", locale))

    explained: set[int] = set()
    every_way = False
    for top in option.get("tops_sold") or []:
        why, pid = top.get("why"), top.get("id")
        sold = next((s for s in option.get("sold") or [] if s["id"] == pid), {})
        if why == "only_way":
            if all(any(other.get("id") == pid for other in o.get("tops_sold") or []) for o in options):
                lines.append(t("plan_to_sign.concl_only_way", locale, name=top["web_name"], target=target))
            elif not every_way:  # every option sells a top, but not the same one: one line, not one per top
                lines.append(t("plan_to_sign.concl_every_way", locale, target=target))
                every_way = True
        elif why == "unavailable":
            line = _availability_line(option, sold, locale)
            if line:
                lines.append(line)
        elif why == "decline" and isinstance(top.get("trend"), dict):
            trend = top["trend"]
            lines.append(t(
                "plan_to_sign.concl_decline", locale, name=top["web_name"], recent=_num(trend.get("form_recent")),
                season=_num(trend.get("form_season")), hard=trend.get("hard_fixtures", 0),
            ))
        else:
            continue
        explained.add(pid)

    for sold in option.get("sold") or []:
        if sold["id"] in explained:
            continue
        line = _availability_line(option, sold, locale)
        if line:
            lines.append(line)
            explained.add(sold["id"])
    for sold in option.get("sold") or []:
        if sold["id"] not in explained and (sold.get("hard_fixtures") or 0) >= HARD_RUN_LINE:
            lines.append(t("plan_to_sign.concl_hard_run", locale, name=sold["web_name"], hard=sold["hard_fixtures"]))
            explained.add(sold["id"])
    for sold in option.get("sold") or []:
        if sold["id"] not in explained and sold.get("availability") == "rotation":
            lines.append(t("plan_to_sign.concl_few_starts", locale, name=sold["web_name"]))
            explained.add(sold["id"])
    eo_line = _eo_line(raw_output, option, locale)
    if eo_line is None:
        return lines[:MAX_CONCLUSIONS]
    # The EO line has a reserved slot; it yields only to a sold player who is out or doubtful.
    sold_unavailable = any(s.get("availability") in ("unavailable", "doubt") for s in option.get("sold") or [])
    if sold_unavailable:
        return (lines + [eo_line])[:MAX_CONCLUSIONS]
    return lines[:MAX_CONCLUSIONS - 1] + [eo_line]


def target_pick_suggestions(candidates: Any, locale: Locale = DEFAULT_LOCALE) -> "tuple[Any, ...] | None":
    """Pick-one chips for an ambiguous plan target: each asks "How do I get {name} ..." about one candidate."""
    from .suggestions import KIND_PROMPT_REWRITE, Suggestion  # noqa: PLC0415

    items = []
    for candidate in candidates or []:
        name = str(candidate.get("web_name") or "").strip()
        if not name:
            continue
        team = str(candidate.get("team_short") or "").strip()
        items.append(Suggestion(
            label=f"{name} ({team})" if team else name,
            send_text=t("plan_to_sign.pick_send", locale, name=f"{name} {team}".strip()),
            kind=KIND_PROMPT_REWRITE,
        ))
    return tuple(items) or None


def plan_one_line(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> str | None:
    """The one-line answer for a plan turn that carries a card (the card shows the rest), or ``None``."""
    options = raw_output.get("options") or []
    if raw_output.get("status") != "ok" or raw_output.get("stage") != "plan" or not options:
        return None
    option = options[hero_index(raw_output)]
    names = [tr["out"]["web_name"] for tr in option["transfers"]]
    if not names:
        return None
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + t("plan_to_sign.one_line_and", locale) + names[-1]
    hit = option.get("hit_cost") or 0
    return t(
        "plan_to_sign.one_line", locale, names=joined, bank=_num(option["bank_after"]),
        hit_part=t("plan_to_sign.one_line_hit", locale, hit=hit) if hit else "",
    )


def _pair(tr: dict[str, Any]) -> tuple[Any, Any]:
    return tr["out"]["id"], tr["in"]["id"]


def _move_text(tr: dict[str, Any]) -> str:
    return f"{tr['out']['web_name']} → {tr['in']['web_name']}"


def option_labels(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> list[str]:
    """One label per option, the same in every view: what the option does differently from option 1.

    "Option 1" for the best plan; "Option N: A → B" for the first move not in option 1, with a second move
    when that is not enough to tell it from another option (never the same label twice). When two options differ
    only in which of option 1's moves they keep, the first such move is named ("with" / "without"). The label is
    also the text a tap sends, so it must stay short and parse back to N (:func:`plan_followup.option_pick`).
    """
    options = raw_output.get("options") or []
    if not options:
        return []
    best = {_pair(tr) for tr in options[0]["transfers"]}
    diffs = []
    for option in options:
        moves = [tr for tr in option["transfers"] if _pair(tr) not in best]
        diffs.append([_move_text(tr) for tr in (moves or option["transfers"])])
    labels = [t("plan_to_sign.chip_option_n", locale, n=1)]
    for index in range(1, len(options)):
        mine = diffs[index]
        k = 1
        while k < len(mine) and any(
            j != index and j != 0 and diffs[j][:k] == mine[:k] for j in range(len(options))
        ):
            k += 1
        moves_text = " + ".join(mine[:k])
        twins = [j for j in range(1, len(options)) if j != index and diffs[j] == mine]
        if twins:  # the diff moves ran out and another option has exactly the same ones
            moves_text = _keeps_note(options, index, twins[0], moves_text, locale)
        labels.append(t("plan_to_sign.chip_option_diff", locale, n=index + 1, moves=moves_text))
    return labels


def _keeps_note(options: list[dict[str, Any]], index: int, twin: int, moves_text: str, locale: Locale) -> str:
    """``moves_text`` plus the first of option 1's moves that this option and its twin treat differently."""
    mine = {_pair(tr) for tr in options[index]["transfers"]}
    theirs = {_pair(tr) for tr in options[twin]["transfers"]}
    for tr in options[0]["transfers"]:
        pair = _pair(tr)
        if (pair in mine) != (pair in theirs):
            key = "plan_to_sign.chip_option_with" if pair in mine else "plan_to_sign.chip_option_without"
            return t(key, locale, moves=moves_text, move=_move_text(tr))
    return moves_text


def option_chips(raw_output: dict[str, Any], locale: Locale = DEFAULT_LOCALE) -> list[dict[str, str]]:
    """``{label, send_text}`` for every option except the hero, in rank order; the tap sends the label itself."""
    labels = option_labels(raw_output, locale)
    hero = hero_index(raw_output)
    return [{"label": label, "send_text": label} for index, label in enumerate(labels) if index != hero]
