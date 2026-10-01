"""i115 -- the jev_router package: catalog sync, the measured decision rule,
failure as escalation, the question-only payload, and "not wired".

No test here reaches TypeSafe. An autouse fixture replaces the real HTTP
boundary (``requests.Session.request``, which ``requests.post`` also goes
through) with one that FAILS the test via ``pytest.fail`` -- a
``BaseException``, so ``route()``'s own ``except Exception`` cannot swallow it
into a quiet escalation (lesson: tests can make paid calls).

What this file pins
-------------------
A. Catalog sync: every tool in ``tool_schema_registry.TOOL_NAMES`` has a
   routing criterion, except the written, reasoned ``CATALOG_EXCEPTIONS``;
   every exception is a real registered tool; every criterion is a real tool.
B. The menu: measured criteria minus ``get_chip_advice``, plus the three
   plans, ``none_of_these`` present.
C. The decision rule on the 14 i108 chip ids, from REAL Jev answers recorded
   in the pilot (eval 4b), with the expected outcome written independently
   per question below -- never derived from the recording.
D. Failure is a decision: no key, timeout, transport error, non-200, bad
   body -> ``path="escalate"``, no exception; exactly one attempt; the
   timeout is read from ``FPL_JEV_TIMEOUT_S`` at call time.
E. Privacy (i114): the outgoing body is ``{model, state, questions}`` with
   ``state`` == the question string, and ``route()`` accepts no context.
F. Not wired: no module of the served path references ``jev_router``.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest
import requests

import fpl_grounded_assistant  # noqa: F401  (tool self-registration)
from fpl_grounded_assistant import tool_schema_registry
from fpl_grounded_assistant.jev_router import router as jr
from fpl_grounded_assistant.jev_router.criteria import CRITERIA, NONE_OPTION, PLANS

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RECORDED = PACKAGE_ROOT / "tests" / "fixtures" / "jev_router_i115_recorded_answers.json"


@pytest.fixture(autouse=True)
def _no_real_typesafe_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    real = requests.Session.request

    def guarded(self: Any, method: str, url: str, *a: Any, **kw: Any) -> Any:
        if "typesafe.ai" in str(url):
            pytest.fail(f"real TypeSafe call attempted from a test: {method} {url}")
        return real(self, method, url, *a, **kw)

    monkeypatch.setattr(requests.Session, "request", guarded)


class _Resp:
    def __init__(self, status: int = 200, body: Any = None, bad_json: bool = False) -> None:
        self.status_code = status
        self._body = body
        self._bad = bad_json

    def json(self) -> Any:
        if self._bad:
            raise ValueError("not json")
        return self._body


class _FakePost:
    """Records every call; returns a canned response or raises."""

    def __init__(self, response: Any = None, raises: BaseException | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, url: str, **kw: Any) -> Any:
        self.calls.append({"url": url, **kw})
        if self.raises is not None:
            raise self.raises
        return self.response


def _ok_body(route: str, chip: str) -> dict[str, Any]:
    return {"answers": {"route": {"choice": route, "confidence": 0.9},
                        "chip": {"choice": chip, "confidence": 0.95}},
            "usage": {"input_tokens": 5138, "output_tokens": 0}}


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(jr.API_KEY_ENV, "test-key-not-real")


# ---------------------------------------------------------------- A. catalog sync

def test_every_registered_tool_has_a_criterion_or_a_written_exception() -> None:
    required = set(tool_schema_registry.TOOL_NAMES) - set(jr.CATALOG_EXCEPTIONS)
    missing = sorted(required - set(CRITERIA))
    assert not missing, (
        f"registered tools with no Jev routing criterion: {missing}. Add a criterion to "
        "jev_router/criteria.py (and re-measure routing), or add the tool to "
        "CATALOG_EXCEPTIONS with the reason it is not routed."
    )


def test_every_exception_is_a_registered_tool_with_a_reason() -> None:
    stale = sorted(set(jr.CATALOG_EXCEPTIONS) - set(tool_schema_registry.TOOL_NAMES))
    assert not stale, f"CATALOG_EXCEPTIONS names tools that are not registered: {stale}"
    assert all(isinstance(r, str) and r.strip() for r in jr.CATALOG_EXCEPTIONS.values())
    assert not set(jr.CATALOG_EXCEPTIONS) & set(CRITERIA), "a tool cannot be both routed and excepted"


def test_every_criterion_names_a_registered_tool() -> None:
    unknown = sorted(set(CRITERIA) - {NONE_OPTION} - set(tool_schema_registry.TOOL_NAMES))
    assert not unknown, f"criteria for tools that are not registered (renamed/removed?): {unknown}"


# ---------------------------------------------------------------- B. menu

def test_menu_excludes_the_chip_tool_and_offers_the_plans() -> None:
    menu = jr.build_menu()
    assert "get_chip_advice" not in menu
    assert jr.CHIP_PLAN in menu and set(PLANS) <= set(menu)
    assert NONE_OPTION in menu
    assert set(menu) == (set(CRITERIA) - jr.MENU_EXCLUDED) | set(PLANS)


def test_every_option_has_a_discriminator() -> None:
    for name, crit in jr.build_menu().items():
        assert isinstance(crit, dict) and str(crit.get("what") or "").strip(), name


# ---------------------------------------------------------------- C. decision rule

#: Written from the question text, independently of the recording:
#: (path, chip, gameweek). Triple captain takes the chip path -- whether TC
#: gets a particular part is i112's question, not the router's.
EXPECTED: dict[str, tuple[str, str | None, int | None]] = {
    "cvg-01": ("chip", "bench_boost", 2),      # "evalúa mi equipo ... bench boost en la fecha 2"
    "cvg-02": ("chip", "bench_boost", 3),      # "bench boost en la fecha 3? Analizá mi plantilla"
    "cvg-03": ("chip", "bench_boost", None),   # "esta fecha"
    "cvg-04": ("chip", "bench_boost", None),   # "la próxima fecha"
    "cvg-05": ("chip", "bench_boost", 2),
    "cvg-09": ("chip", "triple_captain", 2),
    "cvg-10": ("chip", "bench_boost", 2),      # "Fecha 2: ¿bench boost sí o no?"
    "cvg-11": ("chip", "bench_boost", 2),
    "cvg-12": ("chip", "bench_boost", 2),
    "ad-03": ("chip", "wildcard", None),
    "ad-04": ("chip", "triple_captain", None),
    "ad-07": ("chip", "free_hit", None),
    "ad-10": ("chip", "bench_boost", None),    # "esta ronda"
    "ad-05": ("escalate", None, None),         # "¿transfer o guardo el chip?" -- no chip named
}


def _recorded_rows() -> list[dict[str, Any]]:
    return json.loads(RECORDED.read_text(encoding="utf-8"))["rows"]


def test_recording_covers_the_fourteen_chip_ids_three_reps() -> None:
    rows = _recorded_rows()
    assert sorted({r["question_id"] for r in rows}) == sorted(EXPECTED)
    assert len(rows) == 3 * len(EXPECTED)


@pytest.mark.parametrize("row", _recorded_rows(), ids=lambda r: f"{r['question_id']}-rep{r['rep']}")
def test_decision_on_recorded_jev_answers(row: dict[str, Any]) -> None:
    path, chip, gw = EXPECTED[row["question_id"]]
    d = jr.decide(row["answers"], row["question"])
    assert d.path == path, (row["question_id"], d)
    assert d.gameweek == gw
    if path == "chip":
        assert d.chip == chip
        assert d.reason in {"plan", "squad+chip_word"}
    else:
        assert d.reason == "chip_none"


def test_squad_route_without_a_chip_word_escalates() -> None:
    d = jr.decide({"route": {"choice": "get_my_squad"}, "chip": {"choice": "bench_boost"}},
                  "¿Cómo viene mi equipo esta semana?")
    assert (d.path, d.reason) == ("escalate", "not_chip_route")


def test_squad_route_with_a_chip_word_takes_the_chip_path() -> None:
    d = jr.decide({"route": {"choice": "get_my_squad"}, "chip": {"choice": "wildcard"}},
                  "Mirá mi plantilla y decime si tiro el wildcard")
    assert (d.path, d.reason, d.chip) == ("chip", "squad+chip_word", "wildcard")


def test_chip_plan_with_chip_none_escalates() -> None:
    d = jr.decide({"route": {"choice": jr.CHIP_PLAN}, "chip": {"choice": "none"}},
                  "¿Uso el chip esta semana?")
    assert (d.path, d.reason) == ("escalate", "chip_none")


@pytest.mark.parametrize("route_name", ["get_player_snapshot", NONE_OPTION, "get_chip_advice",
                                        "plan_fixture_cell_both_axes_with_players"])
def test_any_other_route_escalates(route_name: str) -> None:
    d = jr.decide({"route": {"choice": route_name}, "chip": {"choice": "bench_boost"}},
                  "¿bench boost en la fecha 2?")
    assert (d.path, d.reason) == ("escalate", "not_chip_route")


def test_malformed_answers_escalate() -> None:
    assert jr.decide({}, "¿bench boost?").reason == "malformed_answer"


# ---------------------------------------------------------------- D. failure is a decision

def test_no_api_key_escalates_without_calling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(jr.API_KEY_ENV, raising=False)
    fake = _FakePost(_Resp(200, _ok_body(jr.CHIP_PLAN, "bench_boost")))
    d = jr.route("¿bench boost en la fecha 2?", post=fake)
    assert (d.path, d.reason) == ("escalate", "no_api_key") and fake.calls == []


@pytest.mark.parametrize("exc,reason", [
    (requests.Timeout("slow"), "timeout"),
    (requests.ConnectionError("down"), "transport_error"),
    (RuntimeError("anything"), "transport_error"),
])
def test_transport_failures_escalate(with_key: None, exc: Exception, reason: str) -> None:
    fake = _FakePost(raises=exc)
    d = jr.route("¿bench boost en la fecha 2?", post=fake)
    assert (d.path, d.reason) == ("escalate", reason)
    assert len(fake.calls) == 1, "no retries"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_non_200_escalates_after_one_attempt(with_key: None, status: int) -> None:
    fake = _FakePost(_Resp(status, {}))
    d = jr.route("¿bench boost en la fecha 2?", post=fake)
    assert (d.path, d.reason) == ("escalate", f"http_{status}")
    assert len(fake.calls) == 1, "no retries"


@pytest.mark.parametrize("resp", [_Resp(200, bad_json=True), _Resp(200, {"no": "answers"})])
def test_unreadable_body_escalates(with_key: None, resp: _Resp) -> None:
    d = jr.route("¿bench boost en la fecha 2?", post=_FakePost(resp))
    assert (d.path, d.reason) == ("escalate", "malformed_response")


def test_ok_response_decides_and_carries_latency_and_tokens(with_key: None) -> None:
    d = jr.route("¿bench boost en la fecha 2?", post=_FakePost(_Resp(200, _ok_body(jr.CHIP_PLAN, "bench_boost"))))
    assert (d.path, d.reason, d.chip, d.gameweek) == ("chip", "plan", "bench_boost", 2)
    assert d.latency_ms is not None and d.input_tokens == 5138


def test_timeout_is_read_at_call_time(with_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePost(_Resp(200, _ok_body(NONE_OPTION, "none")))
    monkeypatch.delenv(jr.TIMEOUT_ENV, raising=False)
    jr.route("hola", post=fake)
    monkeypatch.setenv(jr.TIMEOUT_ENV, "0.35")
    jr.route("hola", post=fake)
    monkeypatch.setenv(jr.TIMEOUT_ENV, "garbage")
    jr.route("hola", post=fake)
    assert [c["timeout"] for c in fake.calls] == [1.0, 0.35, 1.0]


def test_real_transport_is_blocked_by_the_autouse_guard(with_key: None) -> None:
    """The guard must FAIL the test, not be swallowed into an escalation."""
    with pytest.raises(pytest.fail.Exception):
        jr.route("¿bench boost en la fecha 2?")


# ---------------------------------------------------------------- E. question-only payload

_FORBIDDEN_KEYS = {"team_id", "_my_team_id", "user_id", "user", "squad", "picks",
                   "history", "session", "session_id", "messages", "bootstrap"}


def _all_keys(obj: Any) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(_all_keys(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(_all_keys(v) for v in obj)) if obj else set()
    return set()


def test_outgoing_body_is_the_question_and_nothing_else(with_key: None) -> None:
    q = "¿Tiro el bench boost en la fecha 2?"
    fake = _FakePost(_Resp(200, _ok_body(jr.CHIP_PLAN, "bench_boost")))
    jr.route(q, post=fake)
    body = fake.calls[0]["json"]
    assert set(body) == {"model", "state", "questions"}
    assert body["state"] == q
    assert set(body["questions"]) == {"route", "chip"}
    leaked = _all_keys(body["questions"]) & _FORBIDDEN_KEYS
    assert not leaked, f"user/context fields in the Jev request: {sorted(leaked)}"
    assert fake.calls[0]["url"] == jr.JEV_URL


def test_route_accepts_no_context_argument() -> None:
    params = inspect.signature(jr.route).parameters
    assert list(params) == ["question", "post"]
    assert params["post"].kind is inspect.Parameter.KEYWORD_ONLY


# ---------------------------------------------------------------- F. not wired

def test_no_served_module_references_jev_router() -> None:
    served = [p for p in (PACKAGE_ROOT / "fpl_grounded_assistant").rglob("*.py")
              if "jev_router" not in p.parts]
    served.append(PACKAGE_ROOT / "fpl_server.py")
    offenders = [str(p.relative_to(PACKAGE_ROOT)) for p in served
                 if "jev_router" in p.read_text(encoding="utf-8")]
    assert not offenders, f"i115 ships the router UNWIRED; referenced from: {offenders}"


def test_serving_imports_do_not_load_jev_router() -> None:
    """Runtime twin of the text check: a package ``__init__`` that walked its
    submodules would load the router without any file naming it. A fresh
    interpreter, because this test process has already imported it."""
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import fpl_grounded_assistant, fpl_grounded_assistant.harness, fpl_grounded_assistant.orchestrator\n"
        "print(sorted(m for m in sys.modules if 'jev_router' in m))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=PACKAGE_ROOT, env={**__import__("os").environ,
                                                "PYTHONPATH": __import__("os").pathsep.join(sys.path)},
                         timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]", out.stdout
