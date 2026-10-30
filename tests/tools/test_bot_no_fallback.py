"""Unavailable authority is a refusal, never permission for another executor."""
import pytest
import json


def test_local_dm_cannot_fall_back_to_a_cli_turn(tmp_path, monkeypatch, capsys):
    from tools import bot_mode_dm as dm
    payload = tmp_path / 'dm.txt'
    payload.write_text('private DM')
    calls = []
    monkeypatch.setattr(dm, '_run_local_turn', lambda *args: calls.append(args) or 0, raising=False)
    monkeypatch.setattr(dm, '_local_delivery_home', lambda argv: None)
    assert dm._run_delivery(['phi', '-p', 'missing'], str(payload), stdin_file=False) == 1
    assert calls == []
    assert json.loads(capsys.readouterr().out)['reason'] == 'runtime_unavailable'
    assert payload.read_text() == 'private DM'


@pytest.mark.skipif("bot_relay.deliver" not in __import__("tui_gateway.server", fromlist=["_methods"])._methods, reason="PHI does not register the Desktop bot_relay.* RPC methods")
def test_legacy_relay_requires_identity_without_spawning(monkeypatch, tmp_path):
    import tui_gateway.server as srv
    calls = []
    monkeypatch.setenv('PHI_HOME', str(tmp_path))
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: calls.append(a))
    result = srv._methods['bot_relay.deliver'](1, {'profile': 'default', 'message': 'hello'})
    assert result['error']['data']['reason'] == 'invalid_params', result
    assert calls == []
