from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from app.models import NotificationType, User
from app.security import hash_password


@pytest.fixture
def seeded(db):
    user = User(
        username="alice",
        password_hash=hash_password("secret"),
        slack_member_id="U999",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        NotificationType(
            user_id=user.id,
            notify_id="deploy_done",
            name="Deploy",
            template="{service} deploy {status}",
        )
    )
    db.commit()
    return user


def test_notify_success(client, seeded, slack_mock):
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api", "status": "ok"},
        },
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ts": "1234.5678"}
    slack_mock.chat_postMessage.assert_called_once_with(
        channel="U999", text="api deploy ok"
    )


def test_notify_invalid_credentials(client, seeded):
    r = client.post(
        "/notify",
        json={"user": "alice", "pass": "wrong", "notify_id": "deploy_done", "param": {}},
    )
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error": "invalid_credentials"}


def test_notify_unknown_notify_id(client, seeded):
    r = client.post(
        "/notify",
        json={"user": "alice", "pass": "secret", "notify_id": "nope", "param": {}},
    )
    assert r.status_code == 404
    assert r.json() == {"ok": False, "error": "notify_type_not_found"}


def test_notify_missing_params(client, seeded):
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api"},
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "missing_params"
    assert body["missing"] == ["status"]


def test_notify_slack_error(client, seeded, slack_mock):
    slack_mock.chat_postMessage.side_effect = SlackApiError(
        "boom", response=MagicMock()
    )
    r = client.post(
        "/notify",
        json={
            "user": "alice",
            "pass": "secret",
            "notify_id": "deploy_done",
            "param": {"service": "api", "status": "ok"},
        },
    )
    assert r.status_code == 502
    assert r.json()["error"] == "slack_error"


def test_notify_malformed_request_returns_422(client):
    r = client.post("/notify", json={"user": "alice", "notify_id": "x"})
    assert r.status_code == 422
