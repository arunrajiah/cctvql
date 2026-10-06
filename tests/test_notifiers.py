"""
Tests for the ntfy, Telegram and Slack notifiers.

Outgoing HTTP calls are mocked with respx so no network is needed.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from cctvql.notifications.base import NotificationPayload
from cctvql.notifications.ntfy import NtfyNotifier
from cctvql.notifications.slack import SlackNotifier
from cctvql.notifications.telegram import TelegramNotifier

SLACK_URL = "https://hooks.slack.com/services/T000/B000/XXXX"
TELEGRAM_URL = "https://api.telegram.org/bot123:abc/sendMessage"


@pytest.fixture
def payload() -> NotificationPayload:
    return NotificationPayload(
        title="Person detected",
        body="A person was seen at the front door.",
        event_id="evt-1",
        camera_name="front_door",
        snapshot_url="http://nvr/snap.jpg",
    )


@pytest.fixture
def bare_payload() -> NotificationPayload:
    return NotificationPayload(title="Motion", body="Something moved.")


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "notifier,expected",
    [
        (NtfyNotifier(topic=""), False),
        (NtfyNotifier(topic="alerts"), True),
        (TelegramNotifier(bot_token="", chat_id="42"), False),
        (TelegramNotifier(bot_token="123:abc", chat_id=""), False),
        (TelegramNotifier(bot_token="123:abc", chat_id="42"), True),
        (SlackNotifier(webhook_url=""), False),
        (SlackNotifier(webhook_url=SLACK_URL), True),
    ],
)
def test_is_configured(notifier, expected):
    assert notifier.is_configured() is expected


# ---------------------------------------------------------------------------
# ntfy
# ---------------------------------------------------------------------------


@respx.mock
async def test_ntfy_posts_to_server_topic_with_attach(payload):
    route = respx.post("https://ntfy.example.com/alerts").mock(return_value=httpx.Response(200))
    notifier = NtfyNotifier(topic="alerts", server="https://ntfy.example.com/")

    await notifier.send(payload)

    assert route.called
    request = route.calls.last.request
    assert request.content == payload.body.encode()
    assert request.headers["Title"] == "Person detected"
    assert request.headers["Priority"] == "high"
    assert request.headers["Attach"] == "http://nvr/snap.jpg"


@respx.mock
async def test_ntfy_omits_attach_without_snapshot(bare_payload):
    route = respx.post("https://ntfy.sh/alerts").mock(return_value=httpx.Response(200))

    await NtfyNotifier(topic="alerts").send(bare_payload)

    request = route.calls.last.request
    assert request.headers["Title"] == "Motion"
    assert "Attach" not in request.headers


@respx.mock
async def test_ntfy_raises_on_server_error(payload):
    respx.post("https://ntfy.sh/alerts").mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        await NtfyNotifier(topic="alerts").send(payload)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


@respx.mock
async def test_telegram_posts_chat_id_and_text(payload):
    route = respx.post(TELEGRAM_URL).mock(return_value=httpx.Response(200, json={"ok": True}))

    await TelegramNotifier(bot_token="123:abc", chat_id="42").send(payload)

    body = json.loads(route.calls.last.request.content)
    assert body["chat_id"] == "42"
    assert "Person detected" in body["text"]
    assert "A person was seen at the front door." in body["text"]


@respx.mock
async def test_telegram_raises_on_server_error(payload):
    respx.post(TELEGRAM_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        await TelegramNotifier(bot_token="123:abc", chat_id="42").send(payload)


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


@respx.mock
async def test_slack_includes_fields_and_image(payload):
    route = respx.post(SLACK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await SlackNotifier(webhook_url=SLACK_URL).send(payload)

    body = json.loads(route.calls.last.request.content)
    assert body["text"] == "*Person detected*\nA person was seen at the front door."
    assert len(body["attachments"]) == 1
    attachment = body["attachments"][0]
    assert attachment["color"] == "danger"
    assert attachment["image_url"] == "http://nvr/snap.jpg"
    assert {f["title"]: f["value"] for f in attachment["fields"]} == {
        "Camera": "front_door",
        "Event ID": "evt-1",
    }


@respx.mock
async def test_slack_attachments_empty_without_extras(bare_payload):
    route = respx.post(SLACK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await SlackNotifier(webhook_url=SLACK_URL).send(bare_payload)

    body = json.loads(route.calls.last.request.content)
    assert body["text"] == "*Motion*\nSomething moved."
    assert body["attachments"] == []


@respx.mock
async def test_slack_raises_on_server_error(payload):
    respx.post(SLACK_URL).mock(return_value=httpx.Response(500))

    with pytest.raises(httpx.HTTPStatusError):
        await SlackNotifier(webhook_url=SLACK_URL).send(payload)
