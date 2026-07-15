"""send_message: payload com tools e extração de texto + tool_use."""

from app import anthropic_client


class _FakeResponse:
    status_code = 200

    def __init__(self, content):
        self._content = content

    def json(self):
        return {"content": self._content,
                "usage": {"input_tokens": 10, "output_tokens": 5}}


def _patch_post(monkeypatch, content, captured=None):
    def fake_post(url, json=None, headers=None, timeout=None, verify=None):
        if captured is not None:
            captured["payload"] = json
        return _FakeResponse(content)

    monkeypatch.setattr(anthropic_client.httpx, "post", fake_post)


def test_resposta_so_texto(monkeypatch):
    _patch_post(monkeypatch, [{"type": "text", "text": "olá"}])
    reply, tool_input, usage, _ = anthropic_client.send_message(
        "key", [], [{"role": "user", "content": "oi"}])
    assert reply == "olá"
    assert tool_input is None
    assert usage["input_tokens"] == 10


def test_resposta_com_tool_use(monkeypatch):
    _patch_post(monkeypatch, [
        {"type": "text", "text": "olá"},
        {"type": "tool_use", "name": "sugerir_continuacoes",
         "input": {"opcoes": ["a", "b"]}},
    ])
    reply, tool_input, _, _ = anthropic_client.send_message(
        "key", [], [{"role": "user", "content": "oi"}])
    assert reply == "olá"
    assert tool_input == {"opcoes": ["a", "b"]}


def test_tools_entra_no_payload_so_quando_passado(monkeypatch):
    captured = {}
    _patch_post(monkeypatch, [{"type": "text", "text": "x"}], captured)
    anthropic_client.send_message("key", [], [{"role": "user", "content": "oi"}])
    assert "tools" not in captured["payload"]

    tool = {"name": "t", "input_schema": {"type": "object"}}
    anthropic_client.send_message(
        "key", [], [{"role": "user", "content": "oi"}], tools=[tool])
    assert captured["payload"]["tools"] == [tool]
