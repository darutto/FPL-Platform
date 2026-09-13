"""i77 -- the Understat season probe, offline.

Four combinations of (schedule, store) drive ``main()`` end to end and are
read back from what it PRODUCED: the exit code, the ``::annotation::`` line
on stdout, and the ``$GITHUB_OUTPUT`` file it appended to. Nothing here is
asserted from the inputs that asked for the outcome.

No network, ever: the autouse fixture replaces both boundaries of the script
(``read_schedule`` -> soccerdata, ``tactical_store_exists_on_r2`` -> boto3)
with raisers, and every test injects its own fakes through ``main()``'s
keyword hooks. A test that forgets to inject dies loudly instead of dialling
Understat or R2.

Every run reads a CONTROL season first (the one the job is about to ingest,
known to be published). Found on 2026-09-13: a stale soccerdata cache served
``(3, 0)`` for the PUBLISHED 2026-2027, so "empty" alone would have been a
green lie. An empty control is therefore a red "no signal" (exit 2), never a
notice -- pinned below, with the guard mutated on its own.

The frames are the measured ones (2026-09-13): ``(3, 0)`` for an unpublished
season -- three index labels over zero columns -- and ``(380, 17)`` for a
published one. The ``(3, 0)`` shape is a trap the card itself warns about and
the last two tests pin it: ``shape[0]`` is 3, not 0, and ``reset_index()``
makes the frame non-empty.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pandas as pd
import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "probe_understat_season.py"


def _load():
    spec = importlib.util.spec_from_file_location("probe_understat_season_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load()


class _NetworkForbidden(RuntimeError):
    """Raised by the default boundaries: no test may reach Understat or R2."""


def _forbidden(*_a, **_k):
    raise _NetworkForbidden("network boundary reached without a test fake")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(probe, "read_schedule", _forbidden)
    monkeypatch.setattr(probe, "tactical_store_exists_on_r2", _forbidden)
    # Never let the developer's shell leak a real output file into a test.
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)


# --- the measured frames -----------------------------------------------------

def _empty_schedule() -> pd.DataFrame:
    """Shape (3, 0): what soccerdata returns for a season Understat has not
    published. Three index entries, zero columns, ``.empty`` True."""
    frame = pd.DataFrame(index=["league", "season", "game"])
    assert frame.shape == (3, 0) and frame.empty
    return frame


def _published_schedule() -> pd.DataFrame:
    """Shape (380, 17): a full Premier League season of fixtures."""
    columns = [f"c{i}" for i in range(17)]
    frame = pd.DataFrame([[i] * 17 for i in range(380)], columns=columns)
    assert frame.shape == (380, 17) and not frame.empty
    return frame


CONTROL = "2026-2027"   # the season the job ingests; known published
PROBED = "2027-2028"    # the one after it


def _run(tmp_path, schedule, store_exists, argv=("--next-after", CONTROL),
         control_schedule=None):
    """Drive main() with per-season fakes. The control season answers with a
    published frame unless a test says otherwise; any other season answers
    with ``schedule``."""
    control_frame = _published_schedule() if control_schedule is None else control_schedule
    frames = {CONTROL: control_frame}
    out_file = tmp_path / "github_output.txt"
    stdout = io.StringIO()
    code = probe.main(
        [*argv, "--github-output", str(out_file)],
        read_schedule_fn=lambda season: frames.get(season, schedule),
        store_exists_fn=lambda season: store_exists,
        stdout=stdout,
    )
    outputs = {}
    if out_file.exists():
        for line in out_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            outputs[key] = value
    return code, stdout.getvalue(), outputs


# --- the four combinations ---------------------------------------------------

_COMBINATIONS = {
    # id: (schedule factory, store_exists, exit code, outcome, annotation prefix)
    "empty+no-store":     (_empty_schedule,     False, 0, "unpublished",               "::notice::Understat aún no publica 2027-2028"),
    "empty+store":        (_empty_schedule,     True,  0, "unpublished_store_present", "::warning::Understat no publica 2027-2028 pero existe un store"),
    "published+no-store": (_published_schedule, False, 1, "published_no_store",        "::error::Understat publicó 2027-2028: ejecutar la entrega de i73 pendiente"),
    "published+store":    (_published_schedule, True,  0, "published",                 "::notice::Understat publica 2027-2028 (380 partidos"),
}


@pytest.mark.parametrize("combo", sorted(_COMBINATIONS), ids=sorted(_COMBINATIONS))
def test_each_combination_produces_its_exit_code_message_and_outputs(tmp_path, combo):
    make_schedule, store_exists, want_code, want_outcome, want_prefix = _COMBINATIONS[combo]

    code, stdout, outputs = _run(tmp_path, make_schedule(), store_exists)

    assert code == want_code
    assert stdout.startswith(want_prefix), stdout
    assert outputs["outcome"] == want_outcome
    assert outputs["season"] == "2027-2028"
    assert outputs["control_season"] == "2026-2027"
    assert outputs["control_matches"] == "380"
    assert outputs["published"] == ("true" if want_outcome.startswith("published") else "false")
    assert outputs["store_exists"] == ("true" if store_exists else "false")


def test_only_the_rotation_moment_is_red(tmp_path):
    """Exactly one of the four combinations fails the job: Understat has the
    season and we have never stored it."""
    reds = [
        combo for combo, (mk, store, *_rest) in _COMBINATIONS.items()
        if _run(tmp_path, mk(), store)[0] != 0
    ]
    assert reds == ["published+no-store"]


# --- the (3, 0) trap ---------------------------------------------------------

def test_the_empty_frame_reports_zero_matches_not_three(tmp_path):
    """The three rows of the (3, 0) frame are index labels, not fixtures."""
    _code, _stdout, outputs = _run(tmp_path, _empty_schedule(), False)
    assert outputs["matches"] == "0"
    assert _empty_schedule().shape[0] == 3  # the number a naive shape[0] test reads


def test_reset_index_would_turn_the_empty_frame_into_a_published_one():
    """Why the probe classifies the RAW frame: ``understat_client`` applies
    ``reset_index()`` before returning, and that makes (3, 0) look populated."""
    reset = _empty_schedule().reset_index()
    assert reset.shape == (3, 1) and not reset.empty
    assert probe._matches(_empty_schedule()) == 0


# --- --next-after and failures -------------------------------------------------

@pytest.mark.parametrize("season,expected", [
    ("2026-2027", "2027-2028"),
    ("2025-2026", "2026-2027"),
    ("2099-2100", "2100-2101"),
])
def test_next_after_derives_the_following_season(tmp_path, season, expected):
    frames = {season: _published_schedule()}
    out_file = tmp_path / "github_output.txt"
    code = probe.main(
        ["--next-after", season, "--github-output", str(out_file)],
        read_schedule_fn=lambda s: frames.get(s, _empty_schedule()),
        store_exists_fn=lambda s: False, stdout=io.StringIO(),
    )
    outputs = dict(line.partition("=")[::2] for line in out_file.read_text(encoding="utf-8").splitlines())
    assert code == 0
    assert outputs["season"] == expected
    assert outputs["control_season"] == season


@pytest.mark.parametrize("bad", ["2026", "2026-2028", "2026/2027", ""])
def test_a_malformed_season_key_is_a_probe_failure(tmp_path, bad):
    code, stdout, outputs = _run(tmp_path, _empty_schedule(), False, argv=("--next-after", bad))
    assert code == 2
    assert stdout.startswith("::error::sonda de Understat")
    assert outputs == {}


def test_a_failing_schedule_read_is_reported_not_classified(tmp_path):
    out_file = tmp_path / "github_output.txt"
    stdout = io.StringIO()

    def boom(season):
        raise ConnectionError("understat unreachable")

    def read(season):
        if season == CONTROL:
            return _published_schedule()
        raise ConnectionError("understat unreachable")

    code = probe.main(
        ["--season", PROBED, "--control", CONTROL, "--github-output", str(out_file)],
        read_schedule_fn=read, store_exists_fn=lambda s: False, stdout=stdout,
    )
    assert code == 2
    assert "sonda de Understat falló para 2027-2028: ConnectionError" in stdout.getvalue()
    assert "outcome=probe_failed" in out_file.read_text(encoding="utf-8")


def test_a_failing_store_check_is_reported_not_treated_as_absent(tmp_path):
    """Credentials or network trouble on R2 must not read as "no store" --
    that would turn an outage into a false rotation alarm."""
    stdout = io.StringIO()

    def boom(season):
        raise RuntimeError("missing required R2 env vars")

    code = probe.main(
        ["--season", PROBED, "--control", CONTROL],
        read_schedule_fn=lambda s: _published_schedule(), store_exists_fn=boom, stdout=stdout,
    )
    assert code == 2
    assert "RuntimeError: missing required R2 env vars" in stdout.getvalue()


def test_the_default_boundaries_are_the_real_ones_and_are_blocked_here(tmp_path):
    """Without injected fakes main() reaches the module boundaries, which this
    module's autouse fixture has replaced with raisers -> probe failure, never
    a network call."""
    stdout = io.StringIO()
    code = probe.main(["--next-after", CONTROL], stdout=stdout)
    assert code == 2
    assert "_NetworkForbidden" in stdout.getvalue()


# --- the control read: "empty" is never the silent face of "broken" ---------

def test_an_empty_control_is_red_no_signal_not_a_green_notice(tmp_path):
    """The stale-cache finding, replayed: the control (a published season)
    comes back (3, 0). Before this guard the probe said "aún no publica
    2027-2028" with exit 0 -- the silent success the plan forbids."""
    code, stdout, outputs = _run(
        tmp_path, _empty_schedule(), False, control_schedule=_empty_schedule()
    )
    assert code == 2
    assert stdout.startswith("::error::sonda sin señal: la temporada actual 2026-2027 llegó vacía de Understat")
    assert "::notice::" not in stdout
    assert outputs["outcome"] == "no_signal"
    assert outputs["control_matches"] == "0"
    assert "published" not in outputs  # nothing is claimed about the probed season


def test_a_published_control_and_an_empty_next_season_is_the_green_notice(tmp_path):
    code, stdout, outputs = _run(
        tmp_path, _empty_schedule(), False, control_schedule=_published_schedule()
    )
    assert code == 0
    assert stdout.startswith("::notice::Understat aún no publica 2027-2028")
    assert outputs["control_matches"] == "380"
    assert outputs["outcome"] == "unpublished"


def test_an_empty_control_hides_nothing_even_when_the_next_season_looks_published(tmp_path):
    """A published-looking probed frame behind an empty control is still no
    signal: the two reads disagree about whether the scrape works."""
    code, stdout, _outputs = _run(
        tmp_path, _published_schedule(), False, control_schedule=_empty_schedule()
    )
    assert code == 2
    assert stdout.startswith("::error::sonda sin señal")


def test_the_control_is_read_before_the_probed_season(tmp_path):
    order = []

    def read(season):
        order.append(season)
        return _published_schedule()

    probe.main(["--next-after", CONTROL], read_schedule_fn=read,
               store_exists_fn=lambda s: True, stdout=io.StringIO())
    assert order == [CONTROL, PROBED]


def test_a_failing_control_read_is_a_probe_failure_naming_the_control(tmp_path):
    stdout = io.StringIO()

    def boom(season):
        raise ConnectionError("blocked")

    code = probe.main(["--next-after", CONTROL], read_schedule_fn=boom,
                      store_exists_fn=lambda s: False, stdout=stdout)
    assert code == 2
    assert "falló para la temporada de control 2026-2027: ConnectionError" in stdout.getvalue()


@pytest.mark.parametrize("argv,reason", [
    (("--season", PROBED), "--season requires --control"),                     # no control at all
    (("--season", PROBED, "--control", PROBED), "control season must differ"),  # control == probed
    (("--season", PROBED, "--control", "2026"), "not a season key"),             # malformed control
], ids=["no-control", "control-equals-probed", "malformed-control"])
def test_explicit_season_requires_a_distinct_valid_control(tmp_path, argv, reason):
    code, stdout, outputs = _run(tmp_path, _published_schedule(), True, argv=argv)
    assert code == 2
    assert stdout.startswith("::error::sonda de Understat")
    assert reason in stdout, stdout   # each refusal names its own reason
    assert outputs == {}


def test_read_schedule_bypasses_the_soccerdata_cache(monkeypatch):
    """``no_cache=True`` is the first defence: the answer to "has Understat
    published this" must never come from a local cache (the July leagues.json
    that served (3, 0) for a published season)."""
    import types

    calls = []

    class _FakeUnderstat:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def read_schedule(self):
            return _published_schedule()

    fake_sd = types.SimpleNamespace(Understat=_FakeUnderstat)
    monkeypatch.setitem(__import__("sys").modules, "soccerdata", fake_sd)
    real = _load().read_schedule  # unpatched copy of the real boundary
    frame = real("2026-2027")
    assert frame.shape == (380, 17)
    assert calls == [{"leagues": "ENG-Premier League", "seasons": "2026-2027", "no_cache": True}]


# --- the R2 boundary, with a fake client -------------------------------------
# Cannot be exercised for real without credentials; what CAN be pinned is the
# only logic in it: a 404 on the pointer key is "absent", anything else is a
# probe failure, and the key asked for is the one publish uploads first.

class _FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeR2:
    def __init__(self, raise_code: str | None) -> None:
        self.raise_code = raise_code
        self.calls: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str):
        self.calls.append((Bucket, Key))
        if self.raise_code:
            raise _FakeClientError(self.raise_code)
        return {"ContentLength": 1}


def _real_store_check(monkeypatch, fake: _FakeR2):
    from fpl_tactical import publish

    monkeypatch.setattr(publish, "_make_r2_client", lambda: fake)
    monkeypatch.setenv(publish.ENV_R2_BUCKET, "bucket-under-test")
    monkeypatch.setenv(publish.ENV_R2_PREFIX, "prefix-under-test")
    return _load().tactical_store_exists_on_r2  # unpatched copy of the real function


def test_r2_404_on_the_pointer_means_absent(monkeypatch):
    fake = _FakeR2(raise_code="404")
    assert _real_store_check(monkeypatch, fake)("2027-2028") is False
    assert fake.calls == [("bucket-under-test", "prefix-under-test/tactical/2027-2028/_tactical_latest.json")]


def test_r2_200_on_the_pointer_means_present(monkeypatch):
    fake = _FakeR2(raise_code=None)
    assert _real_store_check(monkeypatch, fake)("2026-2027") is True


@pytest.mark.parametrize("code", ["403", "500", "SlowDown"])
def test_any_other_r2_error_propagates_as_a_probe_failure(monkeypatch, code):
    fake = _FakeR2(raise_code=code)
    with pytest.raises(_FakeClientError):
        _real_store_check(monkeypatch, fake)("2027-2028")


def test_the_pointer_key_is_the_one_publish_uploads_first(monkeypatch):
    from fpl_tactical import publish

    fake = _FakeR2(raise_code="404")
    _real_store_check(monkeypatch, fake)("2027-2028")
    assert fake.calls[0][1] == publish._season_transfer_plan("2027-2028")[0][1]
