"""Aplicação FastAPI do chat TeIA.

Rodar:  uvicorn app.main:app --port 8000  (a partir da pasta server/)
"""

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from .config import DEV_SECRET_KEY, SERVER_ROOT, settings
from .database import Base, engine
from .routers import admin, auth, chat, documents

logger = logging.getLogger("teia")

STATIC_DIR = SERVER_ROOT / "static"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    # 'unsafe-inline' porque o frontend é um arquivo único com CSS/JS embutidos;
    # fontes vêm do Google Fonts. Nenhum outro destino externo é permitido.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


def _body_limit_for(path: str) -> int:
    if path.startswith("/api/admin/documents"):
        return settings.kb_max_upload_bytes  # upload da base de conhecimento
    return settings.max_body_bytes


class BodySizeLimitMiddleware:
    """Rejeita corpos acima do limite antes de processar (mitigação de abuso).

    Middleware ASGI puro: além do atalho por Content-Length, conta os bytes
    de fato recebidos e responde 413 antes de repassar o corpo à aplicação.
    Assim um cliente que omite Content-Length (ex.: Transfer-Encoding:
    chunked) ou mente no header não escapa do teto — a memória fica limitada
    ao próprio limite. O corpo lido é bufferizado e reenviado à aplicação.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _body_limit_for(scope.get("path", ""))

        # atalho: rejeita já pelo Content-Length declarado, sem bufferizar
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > limit:
                await self._reject(send)
                return

        body = bytearray()
        trailing = None
        while True:
            message = await receive()
            if message["type"] != "http.request":
                trailing = message
                break
            body.extend(message.get("body", b""))
            if len(body) > limit:
                await self._reject(send)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body),
                        "more_body": False}
            if trailing is not None:
                return trailing
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"),
                        (b"x-content-type-options", b"nosniff")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"Requisi\\u00e7\\u00e3o grande demais."}',
        })


app = FastAPI(title="TeIA Chat", docs_url=None, redoc_url=None)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(documents.router)


@app.get("/admin", include_in_schema=False)
def admin_page():
    # A página é só a casca do painel; todos os dados vêm de /api/admin/*,
    # que exige papel admin no servidor. Sem sessão de admin, a página
    # redireciona para o login.
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


def validate_production_config() -> None:
    """Em produção, recusa subir com configuração insegura. Fora de produção,
    só emite avisos — a conveniência de dev continua intacta."""
    problems = []
    if settings.secret_key == DEV_SECRET_KEY:
        problems.append(
            "TEIA_SECRET_KEY não definida — a chave de desenvolvimento é pública "
            "e permitiria forjar sessões de admin."
        )
    if not settings.cookie_secure:
        problems.append(
            "TEIA_COOKIE_SECURE deve ser true em produção (cookie de sessão só "
            "sobre HTTPS)."
        )
    if "localhost" in settings.frontend_origin or "127.0.0.1" in settings.frontend_origin:
        problems.append(
            f"TEIA_FRONTEND_ORIGIN aponta para localhost ({settings.frontend_origin}); "
            "defina o domínio público real (CORS/cookies dependem dele)."
        )

    if not settings.is_production:
        for msg in problems:
            logger.warning(msg)
        return
    if problems:
        raise RuntimeError(
            "Configuração de produção insegura — o servidor não vai subir:\n  - "
            + "\n  - ".join(problems)
        )


@app.on_event("startup")
def startup():
    validate_production_config()
    # Auto-criar tabelas é conveniência de dev/SQLite. Em produção o schema
    # vem de `alembic upgrade head` — nunca deste atalho (evita drift).
    if settings.auto_create_tables and not settings.is_production:
        Base.metadata.create_all(engine)
    elif settings.auto_create_tables and settings.is_production:
        logger.warning(
            "auto_create_tables ignorado em produção; rode `alembic upgrade head`."
        )
    from .kb import worker
    worker.start()


# estáticos por último, para não engolir as rotas de API
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
