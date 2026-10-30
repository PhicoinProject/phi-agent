"""Mapping repr protection from upstream47668280e7,92d4c0233e,5280dec0ee."""

import ast

import pytest

from agent.redact import redact_sensitive_text, redact_terminal_output


@pytest.mark.parametrize("key", [
    "BRAVE_API_KEY", "access_token", "private_key", "UserPassword", "sessionToken", "clientApiKey",
])
@pytest.mark.parametrize("secret", ["opaque-example-value", b"opaque-example-value", "quote'and\\escape"])
def test_mapping_credentials_are_fully_masked_and_parseable(key, secret):
    result = redact_sensitive_text(repr({key: secret, "token_count": "17"}), force=True)
    parsed = ast.literal_eval(result)
    assert parsed[key] == (b"***" if isinstance(secret, bytes) else "***")
    assert parsed["token_count"] == "17"


def test_source_is_preserved_but_diagnostic_repr_is_masked():
    source = "fixture = {'API_KEY': 'opaque-example-value'}\r\n"
    diagnostic = "E       AssertionError: {'API_KEY': 'opaque-example-value'}\r\n"
    assert redact_terminal_output(source, "cat example.py", force=True) == source
    result = redact_terminal_output(source + diagnostic, "pytest example.py", force=True)
    assert result.startswith(source)
    assert result.endswith("E       AssertionError: {'API_KEY': '***'}\r\n")
    assert "opaque-example-value" not in redact_terminal_output(
        "ValueError: {'sessionToken': 'opaque-example-value'}", force=True,
    )


def test_already_masked_values_and_environment_lookups_survive():
    for value in ("Digest ***", "«redacted:API_KEY»", "os.getenv('API_KEY')"):
        text = repr({"Authorization": value})
        assert redact_sensitive_text(text, force=True) == text
    text = repr({"TOKEN_COUNT": "17", "PASSWORD_POLICY": "strict", "SECRET_NAME": "example"})
    assert redact_sensitive_text(text, force=True) == text


@pytest.mark.parametrize("command", [
    "cat ~/.phi/config.yaml", "cat $PHI_HOME/config.yaml", "cat ${PHI_HOME}/config.yaml",
    "cat $HOME/.phi/config.yaml", "cat ~/.bashrc", "grep token ~/.phi/config.yaml",
    "awk '{print $1; print $2}' ~/.bashrc", "sed -n '1,5p' ~/.zshrc",
])
def test_secret_file_readers_mask_assignments(command):
    text = "SERVICE_TOKEN=opaque-example-value"
    assert "opaque-example-value" not in redact_terminal_output(text, command, force=True)


def test_arbitrary_yaml_and_pattern_named_after_secret_file_remain_source():
    text = "SERVICE_TOKEN=opaque-example-value"
    for command in ("cat config.yaml", "grep .bashrc example.py", "cat example.py"):
        assert redact_terminal_output(text, command, force=True) == text


def test_egress_masks_bearer_without_corrupting_prose_and_fails_closed(monkeypatch):
    from agent import redact

    prose = "the bearer of bad news"
    assert redact.redact_for_egress(prose) == prose
    assert "opaque0123456789abcdef" not in redact.redact_for_egress("Bearer opaque0123456789abcdef")

    def broken(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(redact, "redact_sensitive_text", broken)
    assert redact.redact_for_egress("private test data") == redact.REDACTION_UNAVAILABLE


def test_gateway_and_monitoring_use_fail_closed_shared_egress(monkeypatch):
    from agent import redact
    from agent.monitoring.redaction import redact_for_export
    from gateway.run import _redact_gateway_user_facing_secrets
    from plugins.platforms.a2a.security import redact_outbound

    for emit in (redact_for_export, _redact_gateway_user_facing_secrets, redact_outbound):
        assert "opaque-example-value" not in emit("{'UserPassword': 'opaque-example-value'}")
    assert "example@example.test" not in redact_for_export("contact example@example.test")

    def broken(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(redact, "redact_sensitive_text", broken)
    for emit in (redact_for_export, _redact_gateway_user_facing_secrets, redact_outbound):
        assert emit("private test data") == redact.REDACTION_UNAVAILABLE