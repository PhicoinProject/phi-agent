"""A web chat opened in a room works in that room's directory (design §B).

``session.create`` (Desktop/TUI) and ``/api/pty`` (dashboard chat) take a ``room_id``: the session's
cwd is the room's directory and the turn knows its room. A web chat without one is not bound.
"""

import asyncio
import json

import pytest
from fastapi import HTTPException

from agent import room_binding as rb
from gateway.session_policy import build_policy, policy_scope
from phi_cli import workspace_map as wm
from phi_cli.web_routers.chat_workspaces import resolve_chat_workspace
from phi_cli.workspace_root import workspace_root
from phi_state_runtime import RuntimeStoreError


def test_session_create_with_a_room_works_in_its_directory():
    room = wm.create_room("Desk room")
    policy = build_policy({'room_id': room['room_id'], 'model': 'm'}, {}, profile_terminal=False)
    room_dir = str(workspace_root() / room['room_id'])
    assert policy.cwd == room_dir
    assert json.loads(policy.terminal_json)['TERMINAL_CWD'] == room_dir

    assert rb.current_room() is None
    with policy_scope(policy):
        assert rb.current_room().room_id == room['room_id']
        assert rb.current_room().source == "web"
    assert rb.current_room() is None


def test_session_create_refuses_an_unknown_room_or_a_space():
    space = wm.create_space("Projects")
    for bad in ("!local_nope", space['room_id']):
        with pytest.raises(RuntimeStoreError, match='invalid_params'):
            build_policy({'room_id': bad, 'model': 'm'}, {}, profile_terminal=False)


def test_session_create_without_a_room_is_not_bound(tmp_path):
    policy = build_policy({'cwd': str(tmp_path), 'model': 'm'}, {}, profile_terminal=False)
    assert policy.cwd == str(tmp_path)
    with policy_scope(policy):
        assert rb.current_room() is None


def test_session_create_contract_declares_room_id():
    from tui_gateway.contracts.registry import CANONICAL_METHODS, canonical_param_problems

    contract = CANONICAL_METHODS['session.create']
    assert canonical_param_problems(contract, {'request_id': 'r', 'source': 'gui', 'room_id': '!local_x'}) == []


def test_dashboard_chat_room_id_picks_the_room_dir(tmp_path):
    room = wm.create_room("pty room")
    assert asyncio.run(resolve_chat_workspace({"room_id": room["room_id"]}, None)) == room["path"]
    # The room wins over a stray ?cwd=.
    assert asyncio.run(resolve_chat_workspace(
        {"room_id": room["room_id"], "cwd": str(tmp_path)}, None)) == room["path"]

    with pytest.raises(HTTPException) as unknown:
        asyncio.run(resolve_chat_workspace({"room_id": "!local_nope"}, None))
    assert unknown.value.status_code == 404
    with pytest.raises(HTTPException) as space:
        asyncio.run(resolve_chat_workspace({"room_id": wm.create_space("S")["room_id"]}, None))
    assert space.value.status_code == 400


def test_dashboard_chat_without_a_room_keeps_the_cwd_pick(tmp_path):
    assert asyncio.run(resolve_chat_workspace({"cwd": str(tmp_path)}, None)) == str(tmp_path)
    assert asyncio.run(resolve_chat_workspace({}, None)) is None
