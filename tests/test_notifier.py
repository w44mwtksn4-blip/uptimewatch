"""Embed content and webhook error handling."""

from types import SimpleNamespace

from uptimewatch import notifier as notifier_module
from uptimewatch.config import CheckConfig
from uptimewatch.notifier import GREEN, RED, DiscordNotifier, build_payload
from uptimewatch.state import DOWN, UP, Transition

CHECK = CheckConfig(name="Web", type="http", failure_threshold=3, url="https://example.com")


def fields(payload):
    return {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}


def test_down_embed_is_red_and_has_reason():
    payload = build_payload(Transition("Web", DOWN, error="HTTP 503", failures=3), CHECK)
    embed = payload["embeds"][0]
    assert embed["color"] == RED
    assert "Web" in embed["title"] and "DOWN" in embed["title"]
    assert fields(payload)["Reason"] == "HTTP 503"
    assert "https://example.com" in fields(payload)["Target"]


def test_recovery_embed_is_green_and_has_downtime():
    payload = build_payload(Transition("Web", UP, downtime_seconds=125), CHECK)
    assert payload["embeds"][0]["color"] == GREEN
    assert fields(payload)["Downtime"] == "2m 05s"


def test_mentions_are_disabled():
    payload = build_payload(Transition("Web", DOWN, error="@everyone", failures=3), CHECK)
    assert payload["allowed_mentions"] == {"parse": []}


def fake_response(status, retry_after=None):
    return SimpleNamespace(
        status_code=status,
        headers={},
        json=lambda: {"retry_after": retry_after} if retry_after is not None else {},
    )


def test_rate_limit_is_retried_once(monkeypatch):
    responses = iter([fake_response(429, 0.01), fake_response(204)])
    monkeypatch.setattr(notifier_module.time, "sleep", lambda _s: None)
    sender = DiscordNotifier("https://discord.example/api/webhooks/1/secret")
    monkeypatch.setattr(sender, "_post", lambda _p: next(responses))
    assert sender.send(Transition("Web", DOWN, error="x", failures=3), CHECK) is True


def test_network_error_is_not_fatal_and_does_not_leak_url(monkeypatch, caplog):
    sender = DiscordNotifier("https://discord.example/api/webhooks/1/secret")

    def boom(_payload):
        raise ConnectionError("failed for https://discord.example/api/webhooks/1/secret")

    monkeypatch.setattr(sender, "_post", boom)
    assert sender.send(Transition("Web", DOWN, error="x", failures=3), CHECK) is False
    assert "secret" not in caplog.text


def test_rejected_notification_returns_false(monkeypatch):
    sender = DiscordNotifier("https://discord.example/api/webhooks/1/secret")
    monkeypatch.setattr(sender, "_post", lambda _p: fake_response(404))
    assert sender.send(Transition("Web", DOWN, error="x", failures=3), CHECK) is False
