"""Image delegation preserves native pixels and text-only compatibility."""

from types import SimpleNamespace

import pytest

from tools.delegate_tool_child_run import _build_child_goal_message
from tools.delegate_tool_tasks import _coerce_task_images


def test_image_validation_and_single_task_fallback():
    assert _coerce_task_images([{"images": " image.png "}], None) == ([["image.png"]], None)
    assert _coerce_task_images([{}], ["image.png"]) == ([["image.png"]], None)
    assert _coerce_task_images([{}, {}], ["image.png"]) == ([None, None], None)
    for invalid in ([""], [17], 17, ["image.png"] * 9):
        images, error = _coerce_task_images([{"images": invalid}], None)
        assert images == [] and error


@pytest.mark.parametrize("mode", ["native", "text"])
def test_local_pixels_and_inline_data_follow_inbound_image_policy(tmp_path, monkeypatch, mode):
    from PIL import Image

    path = tmp_path / "example.png"
    Image.new("RGB", (4, 4), "blue").save(path)
    monkeypatch.setenv("PHI_HOME", str(tmp_path))
    monkeypatch.setattr("phi_cli.config.load_config_readonly", lambda: {})
    monkeypatch.setattr("agent.image_routing.decide_image_input_mode", lambda *args, **kwargs: mode)
    inline = "data:image/png;base64,test-inline-image"
    result = _build_child_goal_message("inspect image", [str(path), "https://example.test/image.png", inline], SimpleNamespace())
    if mode == "native":
        assert result[0]["type"] == "text"
        assert result[0]["text"].startswith("inspect image")
        assert str(path) in result[0]["text"]
        urls = [part["image_url"]["url"] for part in result if part["type"] == "image_url"]
        assert len(urls) == 3
        assert urls[0].startswith("data:image/png;base64,")
        assert "https://example.test/image.png" in urls and inline in urls
    else:
        assert str(path) in result and "https://example.test/image.png" in result
        assert "vision_analyze" in result
        assert inline not in result and "base64" not in result


def test_invalid_images_refuse_spawn_before_children_are_built(monkeypatch):
    from tools import delegate_tool
    from tools.registry import registry

    monkeypatch.setattr(delegate_tool, "is_spawn_paused", lambda: False)
    monkeypatch.setattr(delegate_tool, "_get_max_spawn_depth", lambda: 2)
    monkeypatch.setattr(delegate_tool, "_get_max_concurrent_children", lambda: 3)
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: {})
    monkeypatch.setattr(delegate_tool, "_resolve_delegation_credentials", lambda *args: {})

    def forbidden(*args, **kwargs):
        pytest.fail("invalid images must be rejected before child construction")

    monkeypatch.setattr(delegate_tool, "_build_children", forbidden)
    result = registry.dispatch("delegate_task", {"tasks": [{"goal": "Inspect the supplied image", "images": [17]}]}, parent_agent=SimpleNamespace(_delegate_depth=0))
    assert "images" in result