"""Configuração central do servidor TeIA.

Toda variável pode ser definida no .env da raiz do repositório com o
prefixo TEIA_ (ex.: TEIA_DATABASE_URL=postgresql+psycopg2://...).
As chaves da Anthropic (ANTHROPIC_API_KEY*) não levam prefixo — são as
mesmas da demo e ficam apenas em variáveis de ambiente, nunca no banco.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_ROOT = Path(__file__).resolve().parent.parent  # server/
PROJECT_ROOT = SERVER_ROOT.parent                     # raiz do repositório


def load_dotenv() -> None:
    """Carrega o .env da raiz para os.environ (sem sobrescrever o ambiente)."""
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TEIA_", extra="ignore")

    # --- banco -----------------------------------------------------------
    # Padrão: SQLite local (desenvolvimento sem Docker). Com o Postgres do
    # docker-compose: postgresql+psycopg2://teia:teia-dev@localhost:5432/teia
    database_url: str = "sqlite:///" + (SERVER_ROOT / "teia.db").as_posix()
    # Cria as tabelas no startup se não existirem (conveniência de dev/SQLite).
    # Em produção com Postgres, desligue e use `alembic upgrade head`.
    auto_create_tables: bool = True

    # --- tokens e sessão ---------------------------------------------------
    secret_key: str = "dev-secret-inseguro-trocar-antes-de-expor"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    cookie_secure: bool = False  # True em produção (HTTPS)

    # --- Google OAuth (OIDC, Authorization Code + PKCE) --------------------
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # --- Anthropic ----------------------------------------------------------
    anthropic_model: str = "claude-haiku-4-5"
    anthropic_api_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_timeout_seconds: int = 60
    max_reply_tokens: int = 1024

    # --- limites e cotas (defaults; por usuário/tenant ajustável no banco) --
    frontend_origin: str = "http://localhost:8000"
    max_body_bytes: int = 32 * 1024          # corpo máximo de requisição
    max_message_chars: int = 8000            # tamanho máximo de uma mensagem
    max_history_messages: int = 20           # histórico enviado ao modelo
    login_rate_per_minute: int = 10          # tentativas de login por IP
    chat_rate_per_minute: int = 10           # mensagens de chat por usuário
    max_concurrent_chats_per_user: int = 2   # chamadas simultâneas ao modelo
    default_user_daily_messages: int = 100   # cota diária por usuário
    default_org_monthly_messages: int = 10000  # cota mensal por tenant
    default_org_monthly_cost_usd: float = 50.0  # teto mensal (US$) por tenant

    # --- seed ----------------------------------------------------------------
    admin_email: str = "admin@teia.org.br"
    admin_password: str = ""


settings = Settings()
