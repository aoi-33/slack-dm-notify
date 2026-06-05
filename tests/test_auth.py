from app.auth import authenticate_user
from app.models import User
from app.security import hash_password


def _make_user(db):
    user = User(
        username="alice",
        password_hash=hash_password("secret"),
        slack_member_id="U1",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_authenticate_user_success(db):
    _make_user(db)
    user = authenticate_user(db, "alice", "secret")
    assert user is not None
    assert user.username == "alice"


def test_authenticate_user_wrong_password(db):
    _make_user(db)
    assert authenticate_user(db, "alice", "wrong") is None


def test_authenticate_user_unknown_username(db):
    assert authenticate_user(db, "nobody", "secret") is None
