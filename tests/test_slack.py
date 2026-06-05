from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from app.slack import SlackError, send_dm


def test_send_dm_posts_message_and_returns_ts():
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "111.222"}
    ts = send_dm(client, "U123", "hello")
    client.chat_postMessage.assert_called_once_with(channel="U123", text="hello")
    assert ts == "111.222"


def test_send_dm_wraps_slack_api_error():
    client = MagicMock()
    client.chat_postMessage.side_effect = SlackApiError("boom", response=MagicMock())
    with pytest.raises(SlackError):
        send_dm(client, "U123", "hello")
