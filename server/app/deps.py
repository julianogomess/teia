"""Dependências de autenticação e autorização das rotas."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .security import decode_access_token


def client_ip(request: Request) -> str:
    """IP do cliente; atrás do proxy reverso, usa o primeiro X-Forwarded-For."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "?"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Sessão ausente. Faça login.")
    payload = decode_access_token(auth.removeprefix("Bearer ").strip())
    if payload is None:
        raise HTTPException(401, "Sessão inválida ou expirada. Faça login novamente.")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "Conta inexistente ou bloqueada.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Acesso restrito a administradores.")
    return user
