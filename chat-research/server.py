"""
Servidor do chat TeIA — demo multi-tenant.

Serve a página estática (index.html) e expõe:
  POST /api/login  -> autentica o usuário e devolve um token de sessão
  POST /api/chat   -> encaminha a conversa para a API da Anthropic (Sonnet 5),
                      usando a base de conhecimento e a chave de API do tenant
                      identificado pelo token

Tenants da demonstração:
  - "teia" -> responde apenas com base em context/ (marca e princípios da TeIA)
  - "ong"  -> responde apenas com base em examples-ong/ (docs fictícios da ONG)

Cada tenant pode ter sua própria chave de API (variável de ambiente própria),
de modo que a cobrança na Anthropic cai na conta/workspace daquele cliente.
Se a chave do tenant não estiver definida, usa ANTHROPIC_API_KEY como fallback.

Só usa a biblioteca padrão do Python — sem dependências para instalar.

Uso:
  1. crie um arquivo .env na raiz do projeto com: ANTHROPIC_API_KEY=sk-ant-...
     (opcional: ANTHROPIC_API_KEY_TEIA=... e ANTHROPIC_API_KEY_ONG=...)
  2. py server.py
  3. abrir http://localhost:8000 e logar com teia/teia123 ou ong/ong123
"""

import json
import os
import secrets
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
STATIC_DIR = ROOT
ANTHROPIC_MODEL = "claude-haiku-4-5"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
PORT = int(os.environ.get("PORT", "8000"))

# --------------------------------------------------------------------------
# Tenants — DEMONSTRAÇÃO APENAS.
# Em produção: usuários e senhas ficam num banco com hash (bcrypt/argon2),
# e as chaves de API num secrets manager, nunca em código.
# --------------------------------------------------------------------------
TENANTS = {
    "teia": {
        "password": "teia123",
        "label": "TeIA",
        "description": "identidade de marca, princípios e custos de IA da TeIA",
        "context_dir": PROJECT_ROOT / "context",
        "api_key_env": "ANTHROPIC_API_KEY_TEIA",
    },
    "ong": {
        "password": "ong123",
        "label": "Instituto Raízes do Amanhã",
        "description": "documentos institucionais da ONG (missão, projetos, FAQ de doadores)",
        "context_dir": PROJECT_ROOT / "examples-ong",
        "api_key_env": "ANTHROPIC_API_KEY_ONG",
    },
}

# token de sessão -> nome do tenant (memória; some ao reiniciar o servidor)
SESSIONS: dict[str, str] = {}


def load_dotenv():
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_dotenv()


def load_context(context_dir: Path) -> str:
    parts = []
    for path in sorted(context_dir.glob("*.md")):
        parts.append(f"### {path.name}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def build_system_prompt(tenant: dict) -> str:
    context = load_context(tenant["context_dir"])
    return f"""Você é o assistente de chat da TeIA a serviço de: {tenant['label']}.
Sua base de conhecimento cobre: {tenant['description']}.

REGRAS DE ESCOPO (obrigatórias):
1. Responda apenas com base no conteúdo entre as tags <base_de_conhecimento>.
   Não use conhecimento geral sobre o mundo, outras organizações ou fatos
   externos ao que está documentado ali.
2. Se a pergunta não puder ser respondida com esse conteúdo, diga claramente
   que essa informação não está na sua base de conhecimento atual — não
   invente, não especule.
3. Nunca finja ter tomado uma ação (publicar, enviar, decidir) — você apenas
   informa e sugere, seguindo o princípio "a IA sugere, a equipe decide".
4. Mantenha tom institucional, caloroso e sem hype, conforme o linguajar da
   TeIA.

ESTILO DE CONVERSA (obrigatório):
- Responda como uma pessoa conversando, não como um documento. Escreva em
  parágrafos curtos e corridos, como numa troca de mensagens.
- NÃO use formatação Markdown: nada de títulos (#), negrito (**), itálico,
  listas com hífen ou numeração, tabelas ou blocos de código. O chat exibe
  texto puro, então esses símbolos aparecem literalmente para o usuário.
- Seja direto: comece respondendo a pergunta, sem preâmbulos como "Ótima
  pergunta" ou "Com base na minha base de conhecimento".
- Prefira respostas curtas (2 a 4 parágrafos). Se o assunto tiver muitos
  desdobramentos, responda o essencial e ofereça continuar: "quer que eu
  detalhe X?".
- Se precisar enumerar poucos itens, faça isso dentro da própria frase
  ("são três frentes: educação, cultura e segurança alimentar").

<base_de_conhecimento>
{context}
</base_de_conhecimento>
"""


def resolve_api_key(tenant: dict):
    """Chave do tenant (cobrança na conta/workspace do cliente) ou fallback."""
    return os.environ.get(tenant["api_key_env"]) or os.environ.get("ANTHROPIC_API_KEY")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    # ------------------------------------------------------------------ util
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def _authenticate(self):
        """Resolve o tenant a partir do header Authorization: Bearer <token>."""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        username = SESSIONS.get(auth.removeprefix("Bearer ").strip())
        return TENANTS.get(username) if username else None

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_error(403)
            return
        if not file_path.is_file():
            self.send_error(404)
            return
        content_type = "application/octet-stream"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------------ POST
    def do_POST(self):
        if self.path == "/api/login":
            self._handle_login()
        elif self.path == "/api/chat":
            self._handle_chat()
        else:
            self.send_error(404)

    def _handle_login(self):
        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "JSON inválido."})
            return

        username = str(body.get("username", "")).strip().lower()
        password = str(body.get("password", ""))
        tenant = TENANTS.get(username)

        # Demo: comparação direta. Em produção, hash + secrets.compare_digest.
        if tenant is None or password != tenant["password"]:
            self._send_json(401, {"error": "Usuário ou senha inválidos."})
            return

        token = secrets.token_hex(32)
        SESSIONS[token] = username
        self._send_json(200, {"token": token, "label": tenant["label"]})

    def _handle_chat(self):
        tenant = self._authenticate()
        if tenant is None:
            self._send_json(401, {"error": "Sessão inválida ou expirada. Faça login novamente."})
            return

        api_key = resolve_api_key(tenant)
        if not api_key:
            self._send_json(500, {"error": "Nenhuma chave de API configurada para este tenant."})
            return

        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "JSON inválido."})
            return

        messages = body.get("messages", [])
        if not isinstance(messages, list) or not messages:
            self._send_json(400, {"error": "Campo 'messages' é obrigatório."})
            return

        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "system": build_system_prompt(tenant),
            "messages": messages,
        }

        req = urllib.request.Request(
            ANTHROPIC_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            self._send_json(e.code, {"error": f"Erro da API Anthropic: {detail}"})
            return
        except urllib.error.URLError as e:
            self._send_json(502, {"error": f"Falha ao contatar a API Anthropic: {e.reason}"})
            return

        reply_text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        self._send_json(200, {"reply": reply_text})


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"TeIA chat (multi-tenant demo) rodando em http://localhost:{PORT}")
    print("Logins de demonstração: teia/teia123 | ong/ong123")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("AVISO: ANTHROPIC_API_KEY não definida (fallback ausente).")
    server.serve_forever()


if __name__ == "__main__":
    main()
