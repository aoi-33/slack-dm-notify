from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import get_settings


class SlackError(Exception):
    pass


def get_slack_client() -> WebClient:
    return WebClient(token=get_settings().slack_bot_token)


def send_dm(client: WebClient, member_id: str, text: str) -> str:
    try:
        response = client.chat_postMessage(channel=member_id, text=text)
    except SlackApiError as exc:
        raise SlackError(str(exc)) from exc
    return response["ts"]
