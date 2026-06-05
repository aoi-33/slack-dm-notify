from app.config import get_settings


def test_get_settings_reads_env(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SECRET_KEY", "topsecret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    s = get_settings()
    assert s.slack_bot_token == "xoxb-test"
    assert s.secret_key == "topsecret"
    assert s.database_url == "sqlite:///./x.db"


def test_get_settings_has_defaults(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = get_settings()
    assert s.database_url == "sqlite:///./slack_noti.db"
