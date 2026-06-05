from sqlalchemy import select

from app.models import User


def test_register_creates_user_and_redirects(client, db):
    r = client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    user = db.execute(select(User).where(User.username == "bob")).scalar_one()
    assert user.slack_member_id == "U1"


def test_register_duplicate_username(client):
    client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
    )
    r = client.post(
        "/register",
        data={"username": "bob", "password": "pw2", "slack_member_id": "U2"},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_login_success(client):
    client.post(
        "/register",
        data={"username": "bob", "password": "pw", "slack_member_id": "U1"},
    )
    client.post("/logout")
    r = client.post(
        "/login",
        data={"username": "bob", "password": "pw"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_login_invalid(client):
    r = client.post(
        "/login",
        data={"username": "ghost", "password": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 401
