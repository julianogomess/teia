# Chat Interativo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat com chips clicáveis sugeridos pela IA (tool use), Markdown leve renderizado com segurança, fontes consultadas e polimento da tela.

**Architecture:** `send_message` ganha suporte a `tools` e devolve o input do bloco `tool_use` (canal de saída estruturada, sem loop de agente). `build_system_blocks` passa a devolver também as fontes dos trechos. `/api/chat` responde `{reply, options, sources}`. Front continua um único `index.html` vanilla.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (server/), HTML/CSS/JS vanilla (server/static/index.html), API Anthropic via httpx.

**Spec:** `docs/superpowers/specs/2026-07-15-chat-interativo-design.md`

## Global Constraints

- Branch de trabalho: `feat/chat-interativo` (já criada, spec commitada).
- Rodar testes a partir de `server/`: `python -m pytest tests -q` (não usar `cd` persistente — usar `git -C`/subshell ou caminho absoluto; ver `.claude/rules/hooks-cwd-relativo` na memória do projeto).
- Validação: máx. **4** opções, cada uma truncada em **80** caracteres, vazios/não-string descartados.
- Front sem CDN novo, sem `innerHTML` de conteúdo não escapado.
- Copy de UI nova em pt-BR, tom conforme `context/brand.md` (revisão com `revisor-de-marca` na Task 6).
- Suite existente precisa continuar verde ao fim de cada task.

---

### Task 1: `send_message` com tools e retorno de `tool_input`

**Files:**
- Modify: `server/app/anthropic_client.py:56-95`
- Modify: `server/app/kb/classify.py:54`
- Modify: `server/tests/test_kb_units.py:119-134`
- Test: `server/tests/test_anthropic_client.py` (novo)

**Interfaces:**
- Produces: `send_message(api_key, system_blocks, messages, model=None, tools=None) -> Tuple[str, Optional[dict], dict, int]` — retorna `(reply, tool_input, usage, latency_ms)`; `tool_input` é o `input` do primeiro bloco `tool_use` ou `None`.

- [ ] **Step 1: Escrever testes que falham**

Criar `server/tests/test_anthropic_client.py`:

```python
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
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests/test_anthropic_client.py -q)`
Expected: FAIL — `ValueError: too many values to unpack` (send_message ainda retorna 3 valores) e/ou `TypeError` no parâmetro `tools`.

- [ ] **Step 3: Implementar**

Em `server/app/anthropic_client.py`, substituir a assinatura e o final de `send_message`:

```python
def send_message(
    api_key: str,
    system_blocks: List[dict],
    messages: List[dict],
    model: Optional[str] = None,
    tools: Optional[List[dict]] = None,
) -> Tuple[str, Optional[dict], dict, int]:
    """Envia a conversa ao modelo.

    Retorna (texto, tool_input, usage, latência_ms). `tool_input` é o input
    do primeiro bloco tool_use, quando `tools` for oferecido e o modelo
    chamar a ferramenta — canal de saída estruturada, sem loop de agente
    (nunca devolvemos tool_result).
    """
    model = model or settings.anthropic_model
    payload = {
        "model": model,
        "max_tokens": settings.max_reply_tokens,
        "system": system_blocks,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
```

(restante da chamada httpx inalterado) e, após `data = response.json()`:

```python
    reply = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    tool_input = next(
        (block.get("input") for block in data.get("content", [])
         if block.get("type") == "tool_use"),
        None,
    )
    return reply, tool_input, data.get("usage", {}), latency_ms
```

Em `server/app/kb/classify.py:54`, ajustar o desempacotamento:

```python
    reply, _tool_input, _usage, _latency = send_message(
```

Em `server/tests/test_kb_units.py`, os dois `fake_send` passam a devolver 4 valores e aceitar `tools`:

```python
def test_classifica_documento(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None, tools=None):
        return ('["rh/beneficios/ferias", "RH/Contratos", "///"]', None,
                {"input_tokens": 10}, 5)
```

```python
def test_classificacao_resposta_invalida(monkeypatch):
    def fake_send(api_key, system_blocks, messages, model=None, tools=None):
        return ("não sei classificar", None, {}, 5)
```

Atenção: `server/tests/conftest.py` (fixture `fake_anthropic`) ainda devolve 3 valores — ela substitui `app.routers.chat.send_message`, e a rota só muda na Task 3. Não mexer nela agora.

- [ ] **Step 4: Rodar a suite inteira**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests -q)`
Expected: tudo PASS.

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/Juliano Gomes/Documents/Teia" add server/app/anthropic_client.py server/app/kb/classify.py server/tests/test_kb_units.py server/tests/test_anthropic_client.py
git -C "C:/Users/Juliano Gomes/Documents/Teia" commit -m "feat: send_message aceita tools e devolve tool_input"
```

---

### Task 2: `build_system_blocks` devolve fontes

**Files:**
- Modify: `server/app/context_loader.py:71-112`
- Modify: `server/app/routers/chat.py:94-116`
- Test: `server/tests/test_chat_interativo.py` (novo)

**Interfaces:**
- Consumes: `ChunkHit` (dataclass em `app/kb/search.py`: `chunk_id, document_id, filename, text, tags, score`).
- Produces: `build_system_blocks(org, db=None, query=None) -> Tuple[List[dict], List[dict]]` — `(blocks, sources)`; cada source é `{"filename": str, "tags": List[str]}`, deduplicado por arquivo na ordem dos hits. `POST /api/chat` passa a incluir `"sources"` na resposta.

- [ ] **Step 1: Escrever testes que falham**

Criar `server/tests/test_chat_interativo.py`:

```python
"""Chat interativo: fontes consultadas e (Task 3) opções sugeridas."""

from app import context_loader
from app.kb.search import ChunkHit

from .conftest import auth_headers, login


def _hit(filename, tags, text="trecho"):
    return ChunkHit(chunk_id=1, document_id=1, filename=filename,
                    text=text, tags=tags, score=1.0)


def test_build_system_blocks_devolve_fontes(monkeypatch, db, seed):
    monkeypatch.setattr(context_loader, "has_indexed_documents",
                        lambda db, org_id: True)
    hits = [
        _hit("manual.pdf", ["rh/beneficios"]),
        _hit("manual.pdf", ["rh/beneficios"], text="outro trecho"),
        _hit("guia.md", []),
    ]
    monkeypatch.setattr("app.kb.search.search_chunks",
                        lambda db, org_id, query, top_k=8: hits)
    blocks, sources = context_loader.build_system_blocks(
        seed["ong"], db=db, query="férias")
    assert sources == [
        {"filename": "manual.pdf", "tags": ["rh/beneficios"]},
        {"filename": "guia.md", "tags": []},
    ]
    assert "manual.pdf" in blocks[1]["text"]


def test_fallback_pasta_sem_fontes(db, seed):
    blocks, sources = context_loader.build_system_blocks(
        seed["ong"], db=db, query="oi")
    assert sources == []
    assert len(blocks) == 2


def test_chat_responde_sources(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    res = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "oi"}]},
        headers=auth_headers(token),
    )
    assert res.status_code == 200
    assert res.json()["sources"] == []
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests/test_chat_interativo.py -q)`
Expected: FAIL — `build_system_blocks` retorna lista, não tupla (`too many values to unpack` / `KeyError: 'sources'`).

- [ ] **Step 3: Implementar**

Em `server/app/context_loader.py`, trocar assinatura e retornos de `build_system_blocks`:

```python
def build_system_blocks(org: Organization, db=None,
                        query: Optional[str] = None) -> Tuple[List[dict], List[dict]]:
    """Blocos de system prompt + fontes dos trechos usados.

    Retorna (blocks, sources). Com documentos indexados, sources lista os
    arquivos (deduplicados) de onde vieram os trechos; no fallback de pasta
    concatenada, sources é vazio.
    """
```

(importar `Tuple` de `typing`). No ramo indexado:

```python
        parts = []
        sources = []
        vistos = set()
        for hit in search_chunks(db, org.id, query):
            label = hit.filename + (f" · {', '.join(hit.tags)}" if hit.tags else "")
            parts.append(f"[{label}]\n{hit.text}")
            if hit.filename not in vistos:
                vistos.add(hit.filename)
                sources.append({"filename": hit.filename, "tags": hit.tags})
```

e o `return` do ramo vira `return [...], sources` (mesmos blocos de hoje). O `return` final (fallback de pasta) vira `return [...], []`.

Em `server/app/routers/chat.py`, ajustar a chamada (linhas 94-98):

```python
        system_blocks, sources = build_system_blocks(
            org, db=db, query=body.messages[-1].content)
        reply, usage, latency_ms = send_message(api_key, system_blocks, messages)
```

e o retorno da rota (linha 116):

```python
    return {"reply": reply, "sources": sources}
```

- [ ] **Step 4: Rodar a suite inteira**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests -q)`
Expected: tudo PASS (test_chat.py e test_kb_search.py continuam verdes).

- [ ] **Step 5: Commit**

```bash
git -C "C:/Users/Juliano Gomes/Documents/Teia" add server/app/context_loader.py server/app/routers/chat.py server/tests/test_chat_interativo.py
git -C "C:/Users/Juliano Gomes/Documents/Teia" commit -m "feat: /api/chat devolve fontes dos trechos consultados"
```

---

### Task 3: rota `/api/chat` com opções sugeridas + regras de estilo

**Files:**
- Modify: `server/app/routers/chat.py`
- Modify: `server/app/context_loader.py:17-48` (RULES)
- Modify: `server/tests/conftest.py:113-129`
- Test: `server/tests/test_chat_interativo.py` (ampliar)

**Interfaces:**
- Consumes: `send_message(..., tools=...) -> (reply, tool_input, usage, latency_ms)` (Task 1).
- Produces: resposta `{"reply": str, "options": List[str], "sources": List[dict]}`; fixture `fake_anthropic` vira `FakeAnthropicCalls(list)` com atributos configuráveis `reply` e `tool_input`.

- [ ] **Step 1: Atualizar a fixture `fake_anthropic`**

Em `server/tests/conftest.py`, substituir a fixture:

```python
class FakeAnthropicCalls(list):
    """Chamadas capturadas + resposta configurável pelo teste."""
    reply = "resposta de teste"
    tool_input = None


@pytest.fixture()
def fake_anthropic(monkeypatch):
    """Substitui a chamada real ao modelo; captura o que seria enviado."""
    calls = FakeAnthropicCalls()

    def fake_send(api_key, system_blocks, messages, model=None, tools=None):
        calls.append({"api_key": api_key, "system": system_blocks,
                      "messages": messages, "tools": tools})
        usage = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        return calls.reply, calls.tool_input, usage, 42

    monkeypatch.setattr("app.routers.chat.send_message", fake_send)
    return calls
```

- [ ] **Step 2: Escrever testes que falham**

Acrescentar em `server/tests/test_chat_interativo.py`:

```python
def _chat(client, token, texto="oi"):
    return client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": texto}]},
        headers=auth_headers(token),
    )


def test_chat_retorna_opcoes(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {
        "opcoes": ["Como funciona o reembolso?", "Quais são os prazos?"]}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    data = _chat(client, token).json()
    assert data["reply"] == "resposta de teste"
    assert data["options"] == [
        "Como funciona o reembolso?", "Quais são os prazos?"]
    # a ferramenta foi oferecida ao modelo
    assert fake_anthropic[0]["tools"][0]["name"] == "sugerir_continuacoes"


def test_chat_sem_opcoes(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).json()["options"] == []


def test_opcoes_validadas_e_truncadas(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {"opcoes": [
        "   ", "x" * 200, 42, "a", "b", "c", "d"]}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    options = _chat(client, token).json()["options"]
    assert options == ["x" * 80, "a", "b", "c"]  # máx. 4, 80 chars, sem lixo


def test_tool_input_malformado(client, seed, fake_anthropic):
    fake_anthropic.tool_input = {"foo": "bar"}
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    assert _chat(client, token).json()["options"] == []


def test_regras_permitem_markdown_e_ferramenta(client, seed, fake_anthropic):
    token = login(client, "maria@raizes.org.br", "senha-maria-123")
    _chat(client, token)
    system_text = "\n".join(b["text"] for b in fake_anthropic[0]["system"])
    assert "sugerir_continuacoes" in system_text
    assert "Markdown leve" in system_text
```

- [ ] **Step 3: Rodar e confirmar falha**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests/test_chat_interativo.py -q)`
Expected: FAIL — rota ainda desempacota 3 valores do mock (que agora devolve 4) e não devolve `options`.

- [ ] **Step 4: Implementar**

Em `server/app/routers/chat.py`, adicionar após os imports:

```python
import logging

logger = logging.getLogger(__name__)

MAX_OPTIONS = 4
MAX_OPTION_CHARS = 80

SUGERIR_CONTINUACOES_TOOL = {
    "name": "sugerir_continuacoes",
    "description": (
        "Sugere de 2 a 4 continuações curtas para a conversa, quando houver "
        "caminhos claros de aprofundamento. Cada opção é escrita como a "
        "próxima mensagem que o usuário enviaria."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "opcoes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": "Continuações sugeridas, até 80 caracteres cada.",
            }
        },
        "required": ["opcoes"],
    },
}


def _parse_options(tool_input) -> List[str]:
    """Valida o input da ferramenta: máx. 4 opções, 80 chars, sem vazios."""
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("opcoes"), list):
        return []
    options: List[str] = []
    for item in tool_input["opcoes"]:
        if isinstance(item, str) and item.strip():
            options.append(item.strip()[:MAX_OPTION_CHARS])
        if len(options) == MAX_OPTIONS:
            break
    return options
```

Na rota, trocar a chamada e o retorno:

```python
        reply, tool_input, usage, latency_ms = send_message(
            api_key, system_blocks, messages,
            tools=[SUGERIR_CONTINUACOES_TOOL],
        )
```

```python
    if not reply and tool_input:
        # raro: modelo chamou a ferramenta sem escrever texto — segue sem opções
        logger.warning("modelo chamou ferramenta sem texto (org=%s)", org.slug)
        tool_input = None

    _record(...)  # inalterado
    return {"reply": reply, "options": _parse_options(tool_input),
            "sources": sources}
```

Em `server/app/context_loader.py`, na constante `RULES`, substituir o item "NÃO use formatação Markdown..." do bloco ESTILO DE CONVERSA por:

```
- Use formatação Markdown leve quando ajudar a leitura: negrito para
  destaques, itálico, listas curtas com hífen e no máximo subtítulos
  pequenos (###). Nada de tabelas, blocos de código ou títulos grandes.
```

e acrescentar ao final de `RULES`:

```
CONTINUAÇÕES SUGERIDAS:
- Responda sempre em texto corrido. Se — e somente se — houver caminhos
  claros de aprofundamento, chame a ferramenta sugerir_continuacoes ao
  final, com 2 a 4 opções curtas (até 80 caracteres), cada uma escrita como
  a próxima mensagem do usuário (ex.: "Como funciona o reembolso?").
- Não chame a ferramenta quando a resposta encerrar o assunto.
```

- [ ] **Step 5: Rodar a suite inteira**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests -q)`
Expected: tudo PASS.

- [ ] **Step 6: Commit**

```bash
git -C "C:/Users/Juliano Gomes/Documents/Teia" add server/app/routers/chat.py server/app/context_loader.py server/tests/conftest.py server/tests/test_chat_interativo.py
git -C "C:/Users/Juliano Gomes/Documents/Teia" commit -m "feat: opções sugeridas via tool use no /api/chat"
```

---

### Task 4: front — Markdown seguro e botão copiar

**Files:**
- Modify: `server/static/index.html` (CSS ~linha 165-217, JS `addMessage` ~linha 403-416)

**Interfaces:**
- Produces: `renderMarkdown(text) -> string` (HTML seguro), `addMessage(role, text)` renderiza Markdown nas mensagens da IA e inclui botão copiar. Task 5 estende `addMessage` com `extra = {options, sources}`.

- [ ] **Step 1: Implementar o renderer e o botão**

No `<script>` de `server/static/index.html`, antes de `addMessage`, adicionar:

```js
  // Markdown leve e seguro: escapa TODO o HTML primeiro, depois aplica
  // negrito/itálico/código/listas/títulos sobre o texto já escapado.
  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function inlineMd(s) {
    return s
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/\*([^*]+)\*/g, '<i>$1</i>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }

  function renderMarkdown(text) {
    const out = [];
    let list = null;
    for (const line of escapeHtml(text).split('\n')) {
      const item = line.match(/^\s*[-*]\s+(.+)$/);
      if (item) {
        if (!list) { list = []; }
        list.push('<li>' + inlineMd(item[1]) + '</li>');
        continue;
      }
      if (list) { out.push('<ul>' + list.join('') + '</ul>'); list = null; }
      const heading = line.match(/^#{1,4}\s+(.+)$/);
      if (heading) { out.push('<h4>' + inlineMd(heading[1]) + '</h4>'); continue; }
      if (line.trim() !== '') { out.push('<p>' + inlineMd(line) + '</p>'); }
    }
    if (list) { out.push('<ul>' + list.join('') + '</ul>'); }
    return out.join('');
  }
```

Em `addMessage`, trocar o corpo da mensagem:

```js
  function addMessage(role, text) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = role === 'user' ? 'Você' : 'Te[IA]';
    div.appendChild(label);
    const body = document.createElement('span');
    body.className = 'body';
    if (role === 'assistant') {
      body.innerHTML = renderMarkdown(text);  // renderMarkdown já escapou o HTML
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.className = 'copy-btn';
      copy.textContent = 'copiar';
      copy.addEventListener('click', () => {
        navigator.clipboard.writeText(text).then(() => {
          copy.textContent = 'copiado';
          setTimeout(() => { copy.textContent = 'copiar'; }, 1500);
        });
      });
      label.appendChild(copy);
    } else {
      body.textContent = text;
    }
    div.appendChild(body);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }
```

No CSS, ajustar `.msg` (o corpo renderizado não usa mais pre-wrap) e estilos novos — adicionar após o bloco `.msg .label`:

```css
  .msg.assistant { white-space: normal; }
  .msg .body p { margin: 0 0 8px; }
  .msg .body p:last-child, .msg .body ul:last-child { margin-bottom: 0; }
  .msg .body ul { margin: 0 0 8px; padding-left: 20px; }
  .msg .body h4 {
    margin: 10px 0 4px;
    font-family: 'Source Serif 4', serif;
    font-size: 15px;
  }
  .msg .body code {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 13px;
    background: rgba(42, 27, 20, 0.08);
    padding: 1px 4px;
    border-radius: 4px;
  }
  .copy-btn {
    float: right;
    background: none;
    border: none;
    color: inherit;
    opacity: 0.5;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
    padding: 0;
  }
  .copy-btn:hover { opacity: 1; }
```

(`.msg` mantém `white-space: pre-wrap` para as mensagens do usuário.)

- [ ] **Step 2: Verificar no navegador**

Subir o servidor (config `teia` em `.claude/launch.json`, criar se não existir: `runtimeExecutable: "python"`, `runtimeArgs: ["-m", "uvicorn", "app.main:app", "--port", "8000"]` com cwd server — se launch.json não suportar cwd, usar `runtimeArgs: ["-m", "uvicorn", "--app-dir", "server", "app.main:app", "--port", "8000"]`). Na página, validar pelo console do browser (javascript_tool):

```js
renderMarkdown('**a** e *b*\n- item <script>alert(1)</script>\n### T')
```

Expected: `<p><b>a</b> e <i>b</i></p><ul><li>item &lt;script&gt;alert(1)&lt;/script&gt;</li></ul><h4>T</h4>` — sem tag `<script>` viva.

- [ ] **Step 3: Commit**

```bash
git -C "C:/Users/Juliano Gomes/Documents/Teia" add server/static/index.html
git -C "C:/Users/Juliano Gomes/Documents/Teia" commit -m "feat: markdown leve seguro e botão copiar no chat"
```

---

### Task 5: front — chips, fontes e textarea dinâmica

**Files:**
- Modify: `server/static/index.html` (form handler ~linha 418-460, `addMessage` da Task 4, CSS)

**Interfaces:**
- Consumes: resposta `{reply, options, sources}` do `/api/chat` (Task 3); `addMessage` e CSS da Task 4.
- Produces: `sendMessage(text)` (usada pelo form e pelos chips), `addMessage(role, text, extra = {})` com `extra.options: string[]` e `extra.sources: [{filename, tags}]`.

- [ ] **Step 1: Extrair `sendMessage` e ligar opções/fontes**

Substituir o handler do form por:

```js
  async function sendMessage(text) {
    if (!text || sendBtn.disabled) return;

    addMessage('user', text);
    history.push({ role: 'user', content: text });
    sendBtn.disabled = true;

    const pending = document.createElement('div');
    pending.className = 'msg assistant pending';
    pending.textContent = 'tecendo resposta...';
    log.appendChild(pending);
    log.scrollTop = log.scrollHeight;

    try {
      const res = await api('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: history }),
      });
      const data = await res.json();
      pending.remove();

      if (res.status === 401) {
        addMessage('assistant', data.detail || 'Sessão expirada.');
        chatSection.classList.add('hidden');
        loginSection.classList.remove('hidden');
      } else if (!res.ok) {
        addMessage('assistant', `Erro: ${data.detail || 'falha inesperada.'}`);
      } else {
        addMessage('assistant', data.reply,
                   { options: data.options, sources: data.sources });
        history.push({ role: 'assistant', content: data.reply });
      }
    } catch (err) {
      pending.remove();
      addMessage('assistant', `Erro de conexão: ${err.message}`);
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.style.height = '46px';
    sendMessage(text);
  });
```

Em `addMessage(role, text, extra = {})`, após `div.appendChild(body)` e antes de `log.appendChild(div)`:

```js
    if (role === 'assistant' && extra.sources && extra.sources.length) {
      const det = document.createElement('details');
      det.className = 'sources';
      const sum = document.createElement('summary');
      sum.textContent = `Fontes (${extra.sources.length})`;
      det.appendChild(sum);
      const list = document.createElement('div');
      list.textContent = extra.sources
        .map(s => s.filename + (s.tags.length ? ' · ' + s.tags.join(', ') : ''))
        .join('\n');
      det.appendChild(list);
      div.appendChild(det);
    }
    if (role === 'assistant' && extra.options && extra.options.length) {
      const chips = document.createElement('div');
      chips.className = 'chips';
      for (const opt of extra.options) {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'chip';
        chip.textContent = opt;
        chip.addEventListener('click', () => {
          chips.querySelectorAll('.chip').forEach(c => c.disabled = true);
          sendMessage(opt);
        });
        chips.appendChild(chip);
      }
      div.appendChild(chips);
    }
```

Textarea dinâmica — junto dos listeners existentes do `input`:

```js
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
```

CSS novo (após o bloco `.msg .label`):

```css
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 10px;
  }
  .chip {
    background: none;
    border: 1px solid var(--accent-solid);
    color: var(--accent-solid);
    border-radius: 999px;
    padding: 6px 12px;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
    text-transform: none;
    letter-spacing: normal;
    cursor: pointer;
    text-align: left;
  }
  .chip:hover:not(:disabled) { background: var(--accent-solid); color: var(--text-on-dark); }
  .chip:disabled { opacity: 0.4; cursor: default; }
  .sources {
    margin-top: 10px;
    font-size: 12px;
    opacity: 0.75;
  }
  .sources summary {
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }
  .sources div { white-space: pre-line; padding: 4px 0 0 2px; }
```

- [ ] **Step 2: Verificar no navegador**

Com o servidor de preview aberto, simular uma resposta rica pelo console (javascript_tool):

```js
addMessage('assistant', 'Sobre **férias**:\n- 30 dias\n- venda de 10',
  { options: ['Como solicitar?', 'E o décimo terceiro?'],
    sources: [{ filename: 'manual.pdf', tags: ['rh/beneficios'] }] })
```

Verificar via read_page/screenshot: negrito e lista renderizados, dois chips, bloco "Fontes (1)" colapsado que expande ao clique. Clicar num chip deve desabilitar os dois chips (o envio vai falhar sem login — ok para o teste visual). Digitar várias linhas na textarea deve fazê-la crescer até ~120px.

- [ ] **Step 3: Commit**

```bash
git -C "C:/Users/Juliano Gomes/Documents/Teia" add server/static/index.html
git -C "C:/Users/Juliano Gomes/Documents/Teia" commit -m "feat: chips de continuação, fontes e textarea dinâmica no chat"
```

---

### Task 6: verificação final, marca e PR

**Files:**
- Nenhum arquivo novo (correções pontuais se a revisão apontar).

- [ ] **Step 1: Suite completa**

Run: `(cd "C:/Users/Juliano Gomes/Documents/Teia/server" && python -m pytest tests -q)`
Expected: tudo PASS.

- [ ] **Step 2: Revisão de marca**

Rodar o agente `revisor-de-marca` sobre `server/static/index.html` (copy nova: "copiar", "copiado", "Fontes"). Aplicar ajustes apontados e commitar se houver.

- [ ] **Step 3: Verificação ponta a ponta**

Com o servidor de preview rodando e um tenant logável (skill `rodar` cobre o smoke-test de login), enviar uma pergunta real se houver `ANTHROPIC_API_KEY` no ambiente; sem chave, considerar suficiente a verificação mockada das Tasks 4-5 + suite verde.

- [ ] **Step 4: Finalizar branch**

Usar a skill `superpowers:finishing-a-development-branch` — push de `feat/chat-interativo` e PR para `main` com resumo da spec.
