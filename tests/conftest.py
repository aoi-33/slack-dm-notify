from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (モデルを Base.metadata に登録)
from app.db import Base, get_db
from app.main import create_app
from app.slack import get_slack_client


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def TestingSession(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def db(TestingSession):
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def slack_mock():
    mock = MagicMock()
    mock.chat_postMessage.return_value = {"ts": "1234.5678"}
    return mock


@pytest.fixture
def client(TestingSession, slack_mock):
    app = create_app()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_slack_client] = lambda: slack_mock
    return TestClient(app)
