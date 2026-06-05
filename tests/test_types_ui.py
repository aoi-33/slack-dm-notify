from sqlalchemy import select

from app.models import NotificationType


def _register(client, username="alice"):
    client.post(
        "/register",
        data={"username": username, "password": "pw", "slack_member_id": "U999"},
    )


def test_dashboard_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_create_type_and_appears_on_dashboard(client):
    _register(client)
    r = client.post(
        "/types",
        data={"name": "Deploy", "notify_id": "deploy_done", "template": "{x}"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    dash = client.get("/")
    assert "Deploy" in dash.text
    assert "deploy_done" in dash.text


def test_duplicate_notify_id_rejected(client):
    _register(client)
    client.post(
        "/types", data={"name": "A", "notify_id": "dup", "template": "x"}
    )
    r = client.post(
        "/types",
        data={"name": "B", "notify_id": "dup", "template": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_update_type(client, db):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    r = client.post(
        f"/types/{nt.id}",
        data={"name": "A2", "notify_id": "a", "template": "y"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.refresh(nt)
    assert nt.name == "A2"
    assert nt.template == "y"


def test_delete_type(client, db):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    type_id = nt.id
    r = client.post(f"/types/{type_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(NotificationType, type_id) is None


def test_cannot_modify_other_users_type(client, db):
    _register(client, "alice")
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "x"})
    nt = db.execute(select(NotificationType)).scalars().one()
    client.post("/logout")
    _register(client, "bob")
    r = client.post(
        f"/types/{nt.id}",
        data={"name": "hacked", "notify_id": "a", "template": "z"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    db.refresh(nt)
    assert nt.name == "A"


def test_test_send_invokes_slack(client, db, slack_mock):
    _register(client)
    client.post("/types", data={"name": "A", "notify_id": "a", "template": "hi {who}"})
    nt = db.execute(select(NotificationType)).scalars().one()
    r = client.post(f"/types/{nt.id}/test", follow_redirects=False)
    assert r.status_code == 303
    assert slack_mock.chat_postMessage.called
    _, kwargs = slack_mock.chat_postMessage.call_args
    assert kwargs["channel"] == "U999"
    assert kwargs["text"] == "[test] hi <who>"
