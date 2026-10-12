"""ensure_watcher: idempotent launch of the lineup watcher (alive / finished / nothing -> relaunch)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ensure_watcher  # noqa: E402

ARGS = ("gw", "2026-10-12T00:00:00Z", "2026-10-12T23:59:59Z")


class Spawner:
    def __init__(self):
        self.calls = []

    def __call__(self, args, out_path, root):
        self.calls.append(args)
        return 4242


def _folder(tmp_path):
    folder = tmp_path / "trial-output" / "lineup-watch"
    folder.mkdir(parents=True)
    return folder


def test_with_nothing_it_launches_and_records_the_restart(tmp_path):
    spawn = Spawner()
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=lambda p: False, spawn=spawn) == "started"
    folder = tmp_path / "trial-output" / "lineup-watch"
    assert (folder / "gw.pid").read_text() == "4242" and len(spawn.calls) == 1
    assert spawn.calls[0][1:4] == [ARGS[1], ARGS[2], str(folder / "gw.ndjson")]
    assert json.loads((folder / "gw.ndjson").read_text().splitlines()[-1])["watcher_restart"] is True


def test_a_live_process_is_left_alone_and_nothing_is_written(tmp_path):
    folder = _folder(tmp_path)
    (folder / "gw.pid").write_text("777")
    spawn = Spawner()
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=lambda p: p == 777, spawn=spawn) == "running"
    assert spawn.calls == [] and not (folder / "gw.ndjson").exists()


def test_a_dead_pid_is_relaunched(tmp_path):
    folder = _folder(tmp_path)
    (folder / "gw.pid").write_text("777")
    spawn = Spawner()
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=lambda p: False, spawn=spawn) == "started"
    assert len(spawn.calls) == 1


def test_a_garbage_pid_file_is_relaunched(tmp_path):
    folder = _folder(tmp_path)
    (folder / "gw.pid").write_text("not a pid")
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=lambda p: True, spawn=Spawner()) == "started"


def test_the_done_marker_stops_any_relaunch_even_with_no_process(tmp_path):
    folder = _folder(tmp_path)
    (folder / "gw.ndjson.done").write_text("finished")
    spawn = Spawner()
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=lambda p: False, spawn=spawn) == "finished"
    assert spawn.calls == [] and not (folder / "gw.ndjson").exists()


def test_the_first_poll_time_is_passed_only_when_given(tmp_path):
    spawn = Spawner()
    ensure_watcher.ensure(*ARGS, "2026-10-16T12:00:00Z", root=tmp_path, alive=lambda p: False, spawn=spawn)
    assert spawn.calls[0][-1] == "2026-10-16T12:00:00Z"


def test_a_second_call_after_a_launch_is_idempotent(tmp_path):
    spawn = Spawner()
    alive = lambda p: p == 4242  # noqa: E731
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=alive, spawn=spawn) == "started"
    assert ensure_watcher.ensure(*ARGS, root=tmp_path, alive=alive, spawn=spawn) == "running"
    assert len(spawn.calls) == 1


def test_the_real_liveness_check_sees_this_process_and_not_an_unused_pid():
    assert ensure_watcher.pid_alive(os.getpid()) is True
    assert ensure_watcher.pid_alive(2**22 - 3) is False
