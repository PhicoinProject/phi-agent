"""Hosted-room isolation over real OIDC-authenticated ordinary daemon sockets."""
import pytest
from tests.gateway.fixtures.hosted_auth_probe import probe


@pytest.mark.skipif("groups.capabilities" not in __import__("tui_gateway.contracts", fromlist=["METHODS"]).METHODS, reason="PHI does not ship the Desktop Group Chat / bot relay RPC")
def test_two_authenticated_actors_own_separate_hosted_rooms(tmp_path):
    receipt = probe(tmp_path)
    assert receipt['actors'] == ['alice', 'bob']
    assert receipt['rooms'] == ['alice-room', 'bob-room']
    assert receipt['cross_actor_denials'] == 10
    assert receipt['owner_stops'] == 2
