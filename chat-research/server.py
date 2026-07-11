"""
Servidor do chat TeIA.

Serve a página estática (index.html) e expõe POST /api/chat, que
encaminha a conversa para a API da Anthropic (Claude Sonnet 5) com um
system prompt que:
  - injeta a identidade de marca (context/brand.md)
  - injeta os princípios (context/principles.md)
  - restringe as respostas ao conteúdo desses dois arquivos

Só usa a biblioteca padrão do Python — sem dependências para instalar.

Uso:
  1. crie um arquivo .env na raiz do projeto com: ANTHROPIC_API_KEY=sk-ant-...
  2. py server.py
  3. abrir http://localhost:8000
"""

import json
import os
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT
CONTEXT_DIR = ROOT.parent / "context"
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
PORT = int(os.environ.get("PORT", "8000"))


def load_dotenv():
    env_path = ROOT.parent / ".env"
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


def load_context() -> str:
    parts = []
    for name in ("brand.md", "principles.md"):
        path = CONTEXT_DIR / name
        if path.exists():
            parts.append(f"### {name}\n\n{path.read_text(encoding='utf-8')}")
    return "\n\n---\n\n".join(parts)


def build_system_prompt() -> str:
    context = load_context()
    return f"""Você é o assistente de chat oficial da TeIA. Encarne a identidade, o tom e o
vocabulário descritos no material de marca abaixo — ele é a sua única fonte de
conhecimento e a única identidade que você tem.

REGRAS DE ESCOPO (obrigatórias):
1. Responda apenas com base no conteúdo entre as tags <base_de_conhecimento>.
   Não use conhecimento geral sobre o mundo, outras empresas ou fatos externos
   ao que está documentado ali.
2. Se a pergunta não puder ser respondida com esse conteúdo, diga claramente
   que essa informação não está na sua base de conhecimento atual e sugira
   falar com a equipe da TeIA — não invente, não especule.
3. Nunca finja ter tomado uma ação (publicar, enviar, decidir) — você apenas
   informa e sugere, seguindo o princípio "a IA sugere, a equipe decide".
4. Mantenha o tom, o vocabulário-âncora e as regras de linguajar descritos em
   brand.md §3. Evite hype, jargão não traduzido e promessas de automação total.

<base_de_conhecimento>
{context}
</base_de_conhecimento>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "application/octet-stream"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self._send_json(500, {"error": "ANTHROPIC_API_KEY não está configurada no servidor."})
            return

        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "JSON inválido."})
            return

        messages = body.get("messages", [])
        if not isinstance(messages, list) or not messages:
            self._send_json(400, {"error": "Campo 'messages' é obrigatório."})
            return

        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "system": build_system_prompt(),
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
    print(f"TeIA chat rodando em http://localhost:{PORT}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("AVISO: variável de ambiente ANTHROPIC_API_KEY não definida.")
    server.serve_forever()


if __name__ == "__main__":
    main()
