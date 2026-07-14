"""Modelo de dados do servidor TeIA.

organizations  -> tenants (cada um com pasta de conhecimento e env var da chave)
users          -> contas (senha e/ou Google), papel e cota individual
refresh_tokens -> sessões revogáveis (hash do token, nunca o token em si)
usage_events   -> um registro por chamada de IA (tokens, custo, latência)
auth_events    -> tentativas de login (sucesso/falha) para o painel de segurança

Base de conhecimento (ingestão indexada):
documents       -> arquivo ingerido por tenant (original fica no disco)
document_chunks -> trechos de ~700 tokens; embedding opcional (float32 bytes)
tags            -> taxonomia hierárquica por tenant (caminho materializado)
document_tags   -> associação documento<->tag
ingest_jobs     -> fila de processamento no próprio banco
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

# Papéis disponíveis. Para adicionar um papel novo basta incluí-lo aqui e
# tratar suas permissões em deps.py — sem migração estrutural.
#   superadmin -> equipe TeIA: visão e gestão globais (todos os tenants)
#   admin      -> gestor de um tenant: só a própria organização
#   member     -> usuário comum do chat, sem acesso ao painel
ROLES = ("superadmin", "admin", "member")


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


# --- base de conhecimento ----------------------------------------------------

DOCUMENT_STATUSES = ("pending", "processing", "indexed", "error")
TAG_STATUSES = ("approved", "pending", "rejected")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    ext: Mapped[str] = mapped_column(String(10))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    # caminho do original, relativo a server/ (ou absoluto em testes)
    stored_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    # vetor float32 serializado; NULL quando embeddings estão desligados
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    document: Mapped["Document"] = relationship()


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("organization_id", "path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), index=True
    )
    # caminho materializado ("rh/beneficios/ferias"): consulta por prefixo
    # cobre qualquer nível da hierarquia com o índice comum
    path: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    source: Mapped[str] = mapped_column(String(20), default="admin")  # admin | ia
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DocumentTag(Base):
    __tablename__ = "document_tags"
    __table_args__ = (UniqueConstraint("document_id", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), index=True)

    tag: Mapped["Tag"] = relationship()


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    # pending | running | done | error
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
