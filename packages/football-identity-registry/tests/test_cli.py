import json

from football_identity_registry.cli import main


def test_verify_and_queue_commands_are_noninteractive(tmp_path, capsys):
    assert main(["verify", "--root", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    assert main(["queue", "--root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"schema_version": 1, "items": []}
