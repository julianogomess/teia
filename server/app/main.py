"""Aplicação FastAPI do chat TeIA.

Rodar:  uvicorn app.main:app --port 8000  (a partir da pasta server/)
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from .config import SERVER_ROOT, settings
from .database import Base, engine
from .routers import admin, auth, chat

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


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejeita corpos acima do limite antes de processar (mitigação de abuso)."""

    async def dispatch(self, request: Request, call_next):
        limit = settings.max_body_bytes
        if request.url.path.startswith("/api/admin/documents"):
            limit = settings.kb_max_upload_bytes  # upload da base de conhecimento
        length = request.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > limit:
            return JSONResponse({"detail": "Requisição grande demais."}, status_code=413)
        return await call_next(request)


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


@app.get("/admin", include_in_schema=False)
def admin_page():
    # A página é só a casca do painel; todos os dados vêm de /api/admin/*,
    # que exige papel admin no servidor. Sem sessão de admin, a página
    # redireciona para o login.
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.on_event("startup")
def startup():
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    if settings.secret_key == "dev-secret-inseguro-trocar-antes-de-expor":
        logger.warning(
            "TEIA_SECRET_KEY não definida — usando chave de desenvolvimento. "
            "Defina uma chave forte no .env antes de expor o servidor."
        )
    from .kb import worker
    worker.start()


# estáticos por último, para não engolir as rotas de API
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
