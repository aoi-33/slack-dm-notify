import pytest
from sqlalchemy.exc import IntegrityError

from app.models import NotificationType, User


def test_create_user_and_notification_type(db):
    user = User(username="alice", password_hash="h", slack_member_id="U1")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.id is not None
    assert user.created_at is not None

    nt = NotificationType(
        user_id=user.id, notify_id="deploy", name="Deploy", template="{x}"
    )
    db.add(nt)
    db.commit()
    assert nt.id is not None


def test_username_is_unique(db):
    db.add(User(username="alice", password_hash="h", slack_member_id="U1"))
    db.commit()
    db.add(User(username="alice", password_hash="h2", slack_member_id="U2"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_notify_id_unique_per_user(db):
    user = User(username="alice", password_hash="h", slack_member_id="U1")
    db.add(user)
    db.commit()
    db.add(NotificationType(user_id=user.id, notify_id="d", name="A", template="x"))
    db.commit()
    db.add(NotificationType(user_id=user.id, notify_id="d", name="B", template="y"))
    with pytest.raises(IntegrityError):
        db.commit()
