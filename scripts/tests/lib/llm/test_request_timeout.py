from unittest.mock import MagicMock

import requests

from lib.llm.ollama import OllamaClient
from lib.llm.zhipu import ZhipuClient


def _response(payload):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


def test_zhipu_chat_accepts_per_request_timeout() -> None:
    client = ZhipuClient(api_key="test")
    session = MagicMock()
    session.post.return_value = _response(
        {"choices": [{"message": {"content": "{}"}}]},
    )
    client._session = session
    client._do_chat([{"role": "user", "content": "test"}], timeout=17)
    assert session.post.call_args.kwargs["timeout"] == 17


def test_ollama_chat_accepts_per_request_timeout() -> None:
    client = OllamaClient()
    client._session = MagicMock()
    client._session.post.return_value = _response(
        {"message": {"content": "{}"}},
    )
    client._do_chat([{"role": "user", "content": "test"}], timeout=19)
    assert client._session.post.call_args.kwargs["timeout"] == 19


def test_zhipu_session_disables_transport_level_retries() -> None:
    client = ZhipuClient(api_key="test")

    session = client._get_session()
    adapter = session.get_adapter("https://")

    assert isinstance(adapter, requests.adapters.HTTPAdapter)
    assert adapter.max_retries.total == 0
    client.close()
