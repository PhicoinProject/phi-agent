"""Tests for the webhook adapter's ``cron_job`` route mode.

``cron_job`` routes turn an existing cron job into an event-triggered task:
an inbound webhook event fires the referenced job through the same
claimed-run body a manual ``cronjob(action='run')`` uses, instead of
starting a fresh webhook agent session.

Covers:
- The referenced job is fired via ``execute_job_for_event`` with the
  rendered prompt as transient per-run context
- The normal webhook agent session is NOT started (``handle_message``
  never called)
- HTTP returns 202 Accepted immediately
- Startup validation rejects routes that set both ``cron_job`` and
  ``deliver_only``
- ``execute_job_for_event`` resolves refs and fails cleanly on unknowns
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.webhook import WebhookAdapter, _INSECURE_NO_AUTH
import hashlib
import hmac
from contextlib import contextmanager
from contextvars import ContextVar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(routes, **extra_kw) -> WebhookAdapter:
    extra = {"host": "127.0.0.1", "port": 0, "routes": routes}
    extra.update(extra_kw)
    config = PlatformConfig(enabled=True, extra=extra)
    return WebhookAdapter(config)

def _create_app(adapter: WebhookAdapter) -> web.Application:
    app = web.Application()
    app.router.add_post("/webhooks/{route_name}", adapter._handle_webhook)
    return app

async def _drain_background_tasks(adapter: WebhookAdapter) -> None:
    tasks = list(adapter._background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

# ===================================================================
# Core behaviour: event fires the cron job, not a webhook session
# ===================================================================

class TestCronJobTrigger:
    @pytest.mark.asyncio
    async def test_post_fires_job_with_event_context(self):
        routes = {
            "pr-feedback": {
                "secret": _INSECURE_NO_AUTH,
                "cron_job": "review-sweeper",
                "prompt": "PR #{number} received feedback: {review.body}",
            }
        }
        adapter = _make_adapter(routes)

        handle_message_calls = []

        async def _capture(event):
            handle_message_calls.append(event)

        adapter.handle_message = _capture

        fired = []

        def _fake_execute(job_ref, extra_prompt=None):
            fired.append((job_ref, extra_prompt))
            return {"claimed": True, "success": True, "error": None}

        app = _create_app(adapter)
        body = json.dumps(
            {"number": 7, "review": {"body": "needs tests"}}
        ).encode()

        with patch(
            "tools.cronjob_tools.execute_job_for_event",
            side_effect=_fake_execute,
        ):
            async with TestClient(TestServer(app)) as cli:
                resp = await cli.post(
                    "/webhooks/pr-feedback",
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Delivery": "delivery-cron-1",
                        "X-GitHub-Event": "pull_request_review",
                    },
                )
                assert resp.status == 202
                data = await resp.json()
                assert data["status"] == "accepted"
                assert data["cron_job"] == "review-sweeper"
                await _drain_background_tasks(adapter)

        # Job fired exactly once with the rendered prompt as run context
        assert len(fired) == 1
        job_ref, extra_prompt = fired[0]
        assert job_ref == "review-sweeper"
        assert "PR #7 received feedback: needs tests" in extra_prompt
        assert "pull_request_review" in extra_prompt  # event provenance

        # No fresh webhook agent session was started
        assert handle_message_calls == []

    @pytest.mark.asyncio
    async def test_job_failure_does_not_break_http_response(self):
        routes = {
            "flaky": {"secret": _INSECURE_NO_AUTH, "cron_job": "gone-job"}
        }
        adapter = _make_adapter(routes)
        app = _create_app(adapter)

        def _fail(job_ref, extra_prompt=None):
            return {
                "claimed": False,
                "success": False,
                "error": "Cron job 'gone-job' not found.",
            }

        with patch(
            "tools.cronjob_tools.execute_job_for_event", side_effect=_fail
        ):
            async with TestClient(TestServer(app)) as cli:
                resp = await cli.post(
                    "/webhooks/flaky",
                    data=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "X-GitHub-Delivery": "delivery-cron-2",
                    },
                )
                # Fire-and-forget: the POST is accepted even when the job
                # later fails; the failure is logged, not surfaced.
                assert resp.status == 202
                await _drain_background_tasks(adapter)

    @pytest.mark.asyncio
    async def test_routed_profile_scope_reaches_the_job_run(self, tmp_path, monkeypatch):
        """/p/<profile>/ routes must fire the job from THAT profile's cron store, not the gateway's
        default home (and route-level skills stay out of the per-run context — the job's own apply)."""
        home = tmp_path / ".phi"
        (home / "profiles" / "sec").mkdir(parents=True)
        monkeypatch.setenv("PHI_HOME", str(home))
        monkeypatch.setattr("phi_cli.profiles._get_default_phi_home", lambda: home)
        monkeypatch.setattr("phi_cli.profiles._get_profiles_root", lambda: home / "profiles")
        adapter = _make_adapter({"ev": {"secret": _INSECURE_NO_AUTH, "cron_job": "sweeper", "profile": "sec",
                                        "skills": ["some-skill"], "prompt": "hello {n}"}})
        monkeypatch.setattr(adapter, "_resolve_request_profile", lambda request: "sec")
        monkeypatch.setattr(adapter, "_apply_skills", lambda prompt, skills: pytest.fail("skills applied"))
        seen = []

        def _fake_execute(job_ref, extra_prompt=None):
            from phi_constants import get_phi_home
            seen.append((get_phi_home(), extra_prompt))
            return {"claimed": True, "success": True, "error": None}

        with patch("tools.cronjob_tools.execute_job_for_event", side_effect=_fake_execute):
            async with TestClient(TestServer(_create_app(adapter))) as cli:
                resp = await cli.post("/webhooks/ev", data=b'{"n": 1}',
                                      headers={"Content-Type": "application/json", "X-GitHub-Delivery": "d-3"})
                assert resp.status == 202
                await _drain_background_tasks(adapter)
        assert seen and seen[0][0] == (home / "profiles" / "sec").resolve()
        assert "hello 1" in seen[0][1]

# ===================================================================
# Startup validation
# ===================================================================

class TestCronJobRouteValidation:
    @pytest.mark.asyncio
    async def test_cron_job_plus_deliver_only_rejected_at_connect(self):
        routes = {
            "bad": {
                "secret": "s3cret",
                "cron_job": "some-job",
                "deliver_only": True,
                "deliver": "telegram",
            }
        }
        adapter = _make_adapter(routes)
        with pytest.raises(ValueError, match="mutually exclusive"):
            await adapter.connect()

# ===================================================================
# execute_job_for_event unit behaviour
# ===================================================================

class TestExecuteJobForEvent:
    def test_unknown_job_returns_error(self):
        from tools import cronjob_tools

        with patch.object(cronjob_tools, "resolve_job_ref", return_value=None):
            result = cronjob_tools.execute_job_for_event("nope")
        assert result["claimed"] is False
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_ambiguous_ref_returns_error(self):
        from cron.jobs import AmbiguousJobReference
        from tools import cronjob_tools

        with patch.object(
            cronjob_tools,
            "resolve_job_ref",
            side_effect=AmbiguousJobReference(
                "x", [{"id": "job-a"}, {"id": "job-b"}]
            ),
        ):
            result = cronjob_tools.execute_job_for_event("x")
        assert result["claimed"] is False
        assert result["success"] is False
        assert "ambiguous" in result["error"].lower()


# --- PHI guard tests (kept across stable syncs) ---

@pytest.mark.asyncio
async def test_authenticated_trigger_deduplicates_and_preserves_worker_profile(monkeypatch):
    secret = "test-only-webhook-secret"
    adapter = WebhookAdapter(PlatformConfig(enabled=True, extra={
        "host": "127.0.0.1", "port": 0, "routes": {"events": {
            "secret": secret, "cron_job": "job-id", "prompt": "Review {number}", "skills": ["route-skill"],
        }},
    }))
    scope = ContextVar("test_profile", default=None)

    @contextmanager
    def profile_scope(profile):
        token = scope.set("routed-profile")
        try:
            yield
        finally:
            scope.reset(token)

    monkeypatch.setattr(adapter, "_profile_scope", profile_scope)
    fired = []

    def execute(job_ref, context):
        fired.append((job_ref, context, scope.get()))
        return {"success": True}

    def forbidden(*args):
        pytest.fail("cron routes must use job skills and must not create webhook chat sessions")

    monkeypatch.setattr(adapter, "_apply_skills", forbidden)
    monkeypatch.setattr(adapter, "_dispatch_agent_run", forbidden)
    monkeypatch.setattr("tools.cronjob_tools.execute_job_for_event", execute)
    app = web.Application()
    app.router.add_post("/webhooks/{route_name}", adapter._handle_webhook)
    body = json.dumps({"number": 7}).encode()
    headers = {"Content-Type": "application/json", "X-GitHub-Event": "pull_request_review", "X-GitHub-Delivery": "test-delivery"}
    async with TestClient(TestServer(app)) as client:
        rejected = await client.post("/webhooks/events", data=body, headers=headers)
        assert rejected.status in (401, 403)
        assert fired == []
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        accepted = await client.post("/webhooks/events", data=body, headers=headers)
        assert accepted.status == 202
        assert (await accepted.json())["cron_job"] == "job-id"
        await asyncio.gather(*list(adapter._background_tasks))
        duplicate = await client.post("/webhooks/events", data=body, headers=headers)
        assert duplicate.status == 200 and (await duplicate.json())["status"] == "duplicate"
    assert len(fired) == 1
    assert fired[0][0] == "job-id" and fired[0][2] == "routed-profile"
    assert "Review 7" in fired[0][1] and "pull_request_review" in fired[0][1]


def test_direct_delivery_and_cron_are_mutually_exclusive():
    adapter = WebhookAdapter(PlatformConfig(enabled=True, extra={"host": "127.0.0.1"}))
    with pytest.raises(ValueError, match="mutually exclusive"):
        adapter._validate_route("invalid", {"secret": "test", "cron_job": "job", "deliver_only": True, "deliver": "telegram"})


def test_event_executor_uses_claimed_job_and_never_mutates_prompt(monkeypatch):
    from tools import cronjob_tools

    job = {"id": "job", "prompt": "original"}
    monkeypatch.setattr(cronjob_tools, "resolve_job_ref", lambda reference: job if reference == "job" else None)
    seen = []

    def run(resolved, extra_prompt=None):
        seen.append((resolved, extra_prompt))
        return {"claimed": True, "success": True, "error": None}

    monkeypatch.setattr(cronjob_tools, "_execute_job_now", run)
    assert cronjob_tools.execute_job_for_event("job", "event")["success"]
    assert seen == [(job, "event")] and job["prompt"] == "original"
    assert not cronjob_tools.execute_job_for_event("missing")["claimed"]
