import os
from dataclasses import dataclass


@dataclass
class Settings:
    slack_bot_token: str
    secret_key: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
        secret_key=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        database_url=os.environ.get("DATABASE_URL", "sqlite:///./slack_noti.db"),
    )
