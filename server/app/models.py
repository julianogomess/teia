"""Modelo de dados do servidor TeIA.

organizations  -> tenants (cada um com pasta de conhecimento e env var da chave)
users          -> contas (senha e/ou Google), papel e cota individual
refresh_tokens -> sessões revogáveis (hash do token, nunca o token em si)
usage_events   -> um registro por chamada de IA (tokens, custo, latência)
auth_events    -> tentativas de login (sucesso/falha) para o painel de segurança
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Papéis disponíveis. Para adicionar um papel novo basta incluí-lo aqui e
# tratar suas permissões em deps.py — sem migração estrutural.
ROLES = ("admin", "member")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # pasta da base de conhecimento, relativa à raiz do repositório
    context_dir: Mapped[str] = mapped_column(String(255))
    # nome da env var com a chave Anthropic do tenant (a chave nunca vai ao banco)
    api_key_env: Mapped[str] = mapped_column(String(120))
    # cotas mensais; NULL = usa o default de config.py
    monthly_message_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monthly_cost_limit_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[List["User"]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    # NULL para contas que só entram com Google
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # "sub" do OpenID Connect, preenchido no primeiro login com Google
    google_sub: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    # cota diária de mensagens; NULL = usa o default de config.py
    daily_message_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="users")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship()


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    organization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True
    )
    model: Mapped[str] = mapped_column(String(80), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    # ok | error | rate_limited | quota_exceeded
    result: Mapped[str] = mapped_column(String(20), default="ok", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class AuthEvent(Base):
    __tablename__ = "auth_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    # password | google | refresh
    method: Mapped[str] = mapped_column(String(20), default="password")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
