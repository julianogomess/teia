"""Endpoint de chat: valida, aplica limites/cotas, chama o modelo e registra o uso."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..anthropic_client import (
    AnthropicError,
    estimate_cost_usd,
    resolve_api_key,
    send_message,
)
from ..config import settings
from ..context_loader import build_system_blocks
from ..database import get_db
from ..deps import get_current_user
from ..models import UsageEvent, User
from ..quotas import check_quotas
from ..rate_limit import chat_concurrency, chat_limiter

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str = Field(min_length=1)

    @field_validator("role")
    @classmethod
    def role_valido(cls, v: str) -> str:
        if v not in ("user", "assistant"):
            raise ValueError("role deve ser 'user' ou 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def tamanho_maximo(cls, v: str) -> str:
        if len(v) > settings.max_message_chars:
            raise ValueError(
                f"mensagem excede o tamanho máximo de {settings.max_message_chars} caracteres"
            )
        return v


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: List[ChatMessage] = Field(min_length=1, max_length=200)


def _record(db: Session, user: User, result: str, **fields) -> None:
    db.add(
        UsageEvent(
            user_id=user.id,
            organization_id=user.organization_id,
            model=settings.anthropic_model,
            result=result,
            **fields,
        )
    )
    db.commit()


@router.post("/api/chat")
def chat(body: ChatRequest, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    org = user.organization

    # 1. rate limit por usuário (mensagens/minuto)
    if not chat_limiter.hit(f"user:{user.id}", settings.chat_rate_per_minute):
        _record(db, user, "rate_limited")
        raise HTTPException(429, "Muitas mensagens em sequência. Aguarde alguns segundos.")

    # 2. cotas: usuário/dia e tenant/mês (mensagens e custo)
    quota_error = check_quotas(db, user, org)
    if quota_error:
        _record(db, user, "quota_exceeded")
        raise HTTPException(429, quota_error)

    api_key = resolve_api_key(org)
    if not api_key:
        raise HTTPException(503, "Nenhuma chave de API configurada para esta organização.")

    # 3. limite de chamadas simultâneas por usuário
    key = f"user:{user.id}"
    if not chat_concurrency.acquire(key, settings.max_concurrent_chats_per_user):
        raise HTTPException(429, "Você já tem uma resposta em andamento. Aguarde ela terminar.")

    try:
        # histórico truncado: só as últimas N mensagens vão ao modelo
        messages = [m.model_dump() for m in body.messages[-settings.max_history_messages:]]
        system_blocks, sources = build_system_blocks(
            org, db=db, query=body.messages[-1].content)
        reply, usage, latency_ms = send_message(api_key, system_blocks, messages)
    except AnthropicError as exc:
        _record(db, user, "error", latency_ms=0)
        raise HTTPException(502, f"Erro ao consultar o modelo ({exc.status}). Tente novamente.")
    finally:
        chat_concurrency.release(key)

    _record(
        db,
        user,
        "ok",
        input_tokens=usage.get("input_tokens", 0) or 0,
        output_tokens=usage.get("output_tokens", 0) or 0,
        cache_read_tokens=usage.get("cache_read_input_tokens", 0) or 0,
        cache_write_tokens=usage.get("cache_creation_input_tokens", 0) or 0,
        cost_usd=estimate_cost_usd(settings.anthropic_model, usage),
        latency_ms=latency_ms,
    )
    return {"reply": reply, "sources": sources}
