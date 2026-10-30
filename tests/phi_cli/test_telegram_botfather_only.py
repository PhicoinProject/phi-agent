"""Telegram setup is BotFather-only: PHI never calls the Nous managed-bot setup service.

A bot is created with @BotFather, its token pasted, and the allowlist set — from the CLI wizard
or the dashboard's Configure dialog (the generic ``PUT /api/messaging/platforms/telegram``).
"""

import importlib

import pytest

_VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_1234"


def test_managed_bot_client_is_not_importable():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("phi_cli.telegram_managed_bot")


@pytest.fixture
def client():
    try:
        from starlette.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi/starlette not installed")

    from phi_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    c = TestClient(app)
    c.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN
    return c


@pytest.mark.parametrize("method, path", [
    ("POST", "/api/messaging/telegram/onboarding/start"),
    ("GET", "/api/messaging/telegram/onboarding/pairing-1"),
    ("POST", "/api/messaging/telegram/onboarding/pairing-1/apply"),
    ("DELETE", "/api/messaging/telegram/onboarding/pairing-1"),
])
def test_dashboard_onboarding_routes_are_gone(client, method, path):
    assert client.request(method, path).status_code in (404, 405)


def test_cli_wizard_asks_for_botfather_token_first(monkeypatch):
    """No automatic/manual choice: the first question is the (masked) token, an invalid one is
    asked again, and the allowlist lands in .env."""
    import phi_cli.setup as setup_mod
    from phi_cli.config import get_env_value
    from plugins.platforms.telegram.adapter import interactive_setup

    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_HOME_CHANNEL"):
        # Registered then removed, so teardown also undoes the wizard's publish to os.environ.
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    answers = iter(["not-a-token", _VALID_TOKEN, "111, 222"])
    asked = []

    def _prompt(question, default=None, password=False):
        asked.append(password)
        return next(answers)

    monkeypatch.setattr(setup_mod, "prompt", _prompt)
    monkeypatch.setattr(setup_mod, "prompt_yes_no", lambda *_a, **_kw: True)

    interactive_setup()

    assert asked == [True, True, False]
    assert get_env_value("TELEGRAM_BOT_TOKEN") == _VALID_TOKEN
    assert get_env_value("TELEGRAM_ALLOWED_USERS") == "111,222"
