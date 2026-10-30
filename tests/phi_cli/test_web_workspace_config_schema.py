"""The generic Config page's view of ``workspace.*`` (Settings → Workspace owns these).

``workspace.root`` is hidden: changing it moves every room directory, which only the
Move-workspace flow does. ``workspace.default_fence`` is a select over the fence modes the
workspace map accepts, so the form cannot store a value the map would ignore.
"""

from phi_cli import web_server_config
from phi_cli.workspace_map import FENCE_MODES


def test_workspace_root_is_not_in_the_config_schema():
    assert "workspace.root" not in web_server_config.CONFIG_SCHEMA
    # The per-request schema the route serves is derived from CONFIG_SCHEMA; it must not
    # bring the field back.
    assert "workspace.root" not in web_server_config._schema_with_dynamic_provider_options()


def test_other_workspace_fields_stay_visible():
    assert "workspace.max_space_depth" in web_server_config.CONFIG_SCHEMA
    assert "workspace.default_fence" in web_server_config.CONFIG_SCHEMA


def test_default_fence_is_a_select_over_the_map_fence_modes():
    entry = web_server_config.CONFIG_SCHEMA["workspace.default_fence"]
    assert entry["type"] == "select"
    assert entry["options"] == list(FENCE_MODES)
    assert entry["category"] == "workspace"


def test_hidden_keys_survive_a_config_round_trip():
    """Hiding a key from the form must not drop it from config.yaml on save: PUT /api/config
    deep-merges onto the stored config, so a key the form never sends is kept."""
    from phi_cli.config import _deep_merge

    stored = {"workspace": {"root": "/srv/placeholder_root", "max_space_depth": 3}}
    sent = {"workspace": {"max_space_depth": 4, "default_fence": "strict"}}
    merged = _deep_merge(stored, sent)
    assert merged["workspace"] == {
        "root": "/srv/placeholder_root", "max_space_depth": 4, "default_fence": "strict"}
