"""Jev shadow (i116): run the Jev path NEXT TO the served turn, never instead of it.

Off by default. ``FPL_JEV_MODE=shadow`` (read at call time) turns it on;
anything else -- unset, ``off``, a typo, and also ``canary`` until i118 ships
the serving side -- is OFF. Turning it on is a Railway variable, not a deploy.

Where it runs: ``harness.ask_v2``, on the plain-text orchestrator branch,
right after ``ask_orchestrated`` returned -- so it sees the exact text the
orchestrator answered (``cleaned_text``), for ``/ask`` and session turns
alike. The served result is already computed and is never read back from
here: the shadow cannot change what the user gets.

What it does, in a daemon thread (the response never waits for it; a daemon
thread, not an executor, for the reason in ``player_form.py``):

* Layer 1, every shadowed turn: ``jev_router.route(question)`` -- the request
  carries the question text ONLY (i114). Logs the decision.
* Layer 2, only when layer 1 takes the CHIP path: ``get_chip_advice`` run
  deterministically on a private copy of the turn's bootstrap (so a linked
  team is evaluated exactly as in the served path), ONE no-tools provider
  call that writes the body under the i108 E3 rule, and
  ``compose_chip_answer`` -- the measured eval-4b path. The row carries
  ``answer_text_full`` + ``chip_trace`` in the shape
  ``scripts/grade_i108_chip_two_parts.py`` reads, unchanged.

Output: one NDJSON line per shadowed turn in
``<resolve_log_dir()>/shadow_logs/<UTC date>.ndjson`` (the i104 volume),
joined to the audit line by ``turn_id`` (``AuditEntry.turn_id``, set only on
shadowed turns). The shadow line holds no user id and no question text --
the audit line already has both; the join is the only link.

Failure: anything raised inside the thread is caught and logged as a row with
``error``; nothing propagates to the served turn, and ``start`` itself never
raises.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .router import PATH_CHIP, JevDecision, route

_LOG = logging.getLogger(__name__)

MODE_ENV: str = "FPL_JEV_MODE"
MODE_SHADOW: str = "shadow"
SHADOW_SUBDIR: str = "shadow_logs"

#: The routing_trace key the harness sets on a shadowed turn and the server
#: copies into AuditEntry.turn_id. Absent on every non-shadowed turn.
TURN_ID_TRACE_KEY: str = "jev_shadow_turn_id"

_WRITE_LOCK = threading.Lock()


def shadow_enabled() -> bool:
    """``FPL_JEV_MODE == "shadow"`` at call time; everything else is off."""
    return os.environ.get(MODE_ENV, "").strip().lower() == MODE_SHADOW


def new_turn_id() -> str:
    return uuid.uuid4().hex


def shadow_log_path(now: datetime | None = None) -> str:
    from ..audit import resolve_log_dir  # noqa: PLC0415

    day = (now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%d")
    return os.path.join(resolve_log_dir(), SHADOW_SUBDIR, f"{day}.ndjson")


def _spawn_daemon(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="jev-shadow", daemon=True).start()


#: Indirection so tests can run the shadow inline; production spawns a daemon.
_SPAWN: Callable[[Callable[[], None]], None] = _spawn_daemon


def start(
    *,
    turn_id: str,
    question: str,
    bootstrap: dict[str, Any],
    provider: str | None,
    model: str | None,
    api_key: str | None,
    served_tool_sequence: list[str],
) -> None:
    """Fire-and-forget. Never raises into the caller."""
    try:
        _SPAWN(lambda: _run(turn_id=turn_id, question=question, bootstrap=bootstrap,
                            provider=provider, model=model, api_key=api_key,
                            served_tool_sequence=served_tool_sequence))
    except Exception:  # noqa: BLE001 -- a shadow that cannot start is not the user's problem
        _LOG.exception("jev shadow: could not start for turn %s", turn_id)


def _run(
    *,
    turn_id: str,
    question: str,
    bootstrap: dict[str, Any],
    provider: str | None,
    model: str | None,
    api_key: str | None,
    served_tool_sequence: list[str],
) -> None:
    row: dict[str, Any] = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "turn_id": turn_id,
        # Grader compatibility (grade_i108_chip_two_parts reads these names).
        "question_id": turn_id,
        "rep": 0,
        "team_id_present": bool(bootstrap.get("_my_team_id")),
        "served_tool_sequence": list(served_tool_sequence),
        "layer1": None,
        "layer2": None,
        "chip_trace": None,
        "answer_text_full": None,
        "error": None,
    }
    try:
        decision = route(question)
        row["layer1"] = _decision_dict(decision)
        if decision.path == PATH_CHIP:
            row.update(_layer2(decision, question, bootstrap, provider, model, api_key))
    except Exception as exc:  # noqa: BLE001 -- recorded, never propagated
        row["error"] = f"{type(exc).__name__}: {exc}"[:500]
        _LOG.exception("jev shadow: turn %s failed", turn_id)
    _write(row)


def _decision_dict(d: JevDecision) -> dict[str, Any]:
    return {
        "path": d.path, "reason": d.reason, "route": d.route,
        "route_confidence": d.route_confidence, "chip": d.chip,
        "chip_confidence": d.chip_confidence, "gameweek": d.gameweek,
        "range_signal": d.range_signal,
        "latency_ms": d.latency_ms, "input_tokens": d.input_tokens,
    }


_BODY_SYSTEM = (
    "Eres el asistente de Fantasy Premier League de Bendito Fantasy. Respondes en "
    "espanol, breve y concreto.\n"
    "Escribes UNICAMENTE el cuerpo de una respuesta sobre un chip. Reglas:\n"
    "{rule}\n"
    "Salida del tool get_chip_advice para esta pregunta (usala como unica fuente "
    "de datos; no inventes numeros ni jugadores):\n{payload}\n"
)


def _layer2(
    decision: JevDecision,
    question: str,
    bootstrap: dict[str, Any],
    provider: str | None,
    model: str | None,
    api_key: str | None,
) -> dict[str, Any]:
    from ..chip_two_part import chip_composition_rule, compose_chip_answer  # noqa: PLC0415
    from ..model_pricing import cost_usd  # noqa: PLC0415
    from ..orchestrator import _MODEL_HIDDEN_FIELDS, _extract_text_from_response  # noqa: PLC0415
    from ..provider_client import call_orch_provider  # noqa: PLC0415
    from ..tool_dispatch import run_tool  # noqa: PLC0415

    t0 = time.perf_counter()
    args: dict[str, Any] = {"chip": decision.chip}
    if decision.gameweek is not None:
        args["gameweek"] = decision.gameweek
    # A private copy: run_tool attaches the linked squad onto the dict it gets.
    output = run_tool("get_chip_advice", args, dict(bootstrap))

    hidden = _MODEL_HIDDEN_FIELDS.get("get_chip_advice", frozenset())
    payload = json.dumps({k: v for k, v in output.items() if k not in hidden},
                         ensure_ascii=False, default=str)
    body = ""
    tokens = (0, 0, 0)
    if provider and model:
        call = call_orch_provider(
            provider, model=model,
            system=_BODY_SYSTEM.format(rule=chip_composition_rule(), payload=payload),
            tools=[], messages=[{"role": "user", "content": question}],
            max_tokens=1024, temperature=None, top_p=None, api_key=api_key,
        )
        if call.response is not None:
            body = _extract_text_from_response(call.response, provider) or ""
        tokens = (call.input_tokens or 0, call.output_tokens or 0, call.cache_read_tokens or 0)

    actual = bootstrap.get("bootstrap") if isinstance(bootstrap.get("bootstrap"), dict) else bootstrap
    team_names = {t.get("id"): t.get("name") for t in (actual.get("teams") or [])
                  if isinstance(t, dict) and t.get("id") is not None and t.get("name")}
    answer = compose_chip_answer(body, output, team_names)
    return {
        "layer2": {
            "chip_args": args,
            "tool_status": output.get("status"),
            "body_chars": len(body),
            "input_tokens": tokens[0], "output_tokens": tokens[1], "cache_read_tokens": tokens[2],
            "cost_usd": cost_usd(*tokens, model=model, provider=provider),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        },
        "chip_trace": project_chip_output(output),
        "answer_text_full": answer,
    }


def project_chip_output(output: dict[str, Any]) -> dict[str, Any]:
    """The fields the i108 E3 grader reads -- the same projection
    ``scripts/measure_tool_routing.extract_chip_trace`` writes."""
    signals = output.get("signals") if isinstance(output.get("signals"), dict) else {}
    return {
        "status": output.get("status"),
        "chip": output.get("chip"),
        "recommendation": output.get("recommendation"),
        "squad_source": output.get("squad_source"),
        "squad_fit": output.get("squad_fit"),
        "linked_squad_error": output.get("linked_squad_error"),
        "favoured_teams": [
            {"team": t.get("team"), "team_short": t.get("team_short")}
            for t in signals.get("favoured_teams") or [] if isinstance(t, dict)
        ],
        "favoured_players": [
            {"element": p.get("element"), "web_name": p.get("web_name")}
            for p in signals.get("favoured_players") or [] if isinstance(p, dict)
        ],
    }


def _write(row: dict[str, Any]) -> None:
    try:
        path = shadow_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:  # noqa: BLE001
        _LOG.exception("jev shadow: could not write row for turn %s", row.get("turn_id"))
