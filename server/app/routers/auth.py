"""Autenticação: e-mail/senha, Google (OIDC + PKCE) e sessão via refresh token.

Fluxo de sessão:
- login (senha ou Google) emite um JWT de acesso curto (15 min) e grava um
  refresh token revogável (só o hash vai ao banco) num cookie HttpOnly;
- o frontend renova o acesso via POST /api/auth/refresh (rotação de token);
- logout revoga o refresh token.

Google: cadastro NÃO é aberto — o e-mail precisa ter sido convidado por um
admin (existir em users). No primeiro login, o "sub" do Google é vinculado.
"""

import base64
import hashlib
import secrets
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

import httpx
import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import anthropic_client
from ..config import settings
from ..database import get_db
from ..deps import client_ip
from ..models import AuthEvent, RefreshToken, User
from ..rate_limit import login_limiter
from ..security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    refresh_expiry,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "teia_refresh"
OAUTH_COOKIE = "teia_oauth"

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"

_jwks_client: Optional[pyjwt.PyJWKClient] = None


# --------------------------------------------------------------------- helpers
def _user_payload(user: User) -> dict:
    return {
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "org_label": user.organization.name,
    }


def _record_auth(db: Session, email: str, ip: str, method: str, success: bool,
                 detail: Optional[str] = None) -> None:
    db.add(AuthEvent(email=email[:255], ip=ip, method=method, success=success, detail=detail))
    db.commit()


def _issue_session(db: Session, user: User, response: Response) -> dict:
    raw, token_hash = new_refresh_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash, expires_at=refresh_expiry()))
    db.commit()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )
    return {
        "access_token": create_access_token(user.id, user.role, user.organization_id),
        "user": _user_payload(user),
    }


# ---------------------------------------------------------------- senha local
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not login_limiter.hit(f"ip:{ip}", settings.login_rate_per_minute):
        _record_auth(db, body.email, ip, "password", False, "rate_limited")
        raise HTTPException(429, "Muitas tentativas de login. Aguarde um minuto.")

    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        _record_auth(db, email, ip, "password", False, "credenciais inválidas")
        raise HTTPException(401, "E-mail ou senha inválidos.")

    _record_auth(db, email, ip, "password", True)
    return _issue_session(db, user, response)


# ------------------------------------------------------------------- refresh
@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(401, "Sessão ausente.")
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    if (
        token is None
        or token.revoked_at is not None
        or token.expires_at < datetime.utcnow()
    ):
        raise HTTPException(401, "Sessão inválida ou expirada. Faça login novamente.")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Conta inexistente ou bloqueada.")

    # rotação: o token usado é revogado e um novo é emitido
    token.revoked_at = datetime.utcnow()
    db.commit()
    return _issue_session(db, user, response)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        token = db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
        )
        if token is not None and token.revoked_at is None:
            token.revoked_at = datetime.utcnow()
            db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


# ------------------------------------------------------- Google (OIDC + PKCE)
def _exchange_code(code: str, verifier: str) -> dict:
    """Troca o authorization code por tokens no endpoint do Google."""
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
        timeout=15,
        verify=anthropic_client.SSL_CONTEXT,
    )
    if resp.status_code != 200:
        raise HTTPException(502, "Falha ao trocar o código com o Google.")
    return resp.json()


def _verify_id_token(id_token: str) -> dict:
    """Valida assinatura, audiência e emissor do id_token (JWKS do Google)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = pyjwt.PyJWKClient(GOOGLE_JWKS_URL)
    signing_key = _jwks_client.get_signing_key_from_jwt(id_token)
    return pyjwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.google_client_id,
        issuer=["https://accounts.google.com", "accounts.google.com"],
    )


@router.get("/google/login")
def google_login(request: Request):
    if not settings.google_client_id:
        raise HTTPException(503, "Login com Google não está configurado neste servidor.")
    ip = client_ip(request)
    if not login_limiter.hit(f"ip:{ip}", settings.login_rate_per_minute):
        raise HTTPException(429, "Muitas tentativas de login. Aguarde um minuto.")

    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    response = RedirectResponse(f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}", status_code=302)
    # estado + verifier assinados num cookie de vida curta (não há sessão ainda)
    state_jwt = pyjwt.encode(
        {"state": state, "verifier": verifier, "type": "oauth_state",
         "exp": datetime.utcnow() + timedelta(minutes=10)},
        settings.secret_key,
        algorithm="HS256",
    )
    response.set_cookie(
        OAUTH_COOKIE, state_jwt, max_age=600, httponly=True,
        secure=settings.cookie_secure, samesite="lax", path="/api/auth",
    )
    return response


@router.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db),
                    code: Optional[str] = None, state: Optional[str] = None,
                    error: Optional[str] = None):
    ip = client_ip(request)
    if error or not code or not state:
        return RedirectResponse("/?error=google", status_code=302)

    state_jwt = request.cookies.get(OAUTH_COOKIE, "")
    try:
        saved = pyjwt.decode(state_jwt, settings.secret_key, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        return RedirectResponse("/?error=google", status_code=302)
    if saved.get("type") != "oauth_state" or not secrets.compare_digest(saved.get("state", ""), state):
        return RedirectResponse("/?error=google", status_code=302)

    tokens = _exchange_code(code, saved["verifier"])
    try:
        claims = _verify_id_token(tokens.get("id_token", ""))
    except pyjwt.PyJWTError:
        _record_auth(db, "", ip, "google", False, "id_token inválido")
        return RedirectResponse("/?error=google", status_code=302)

    email = str(claims.get("email", "")).strip().lower()
    sub = str(claims.get("sub", ""))
    if not email or not claims.get("email_verified", False):
        _record_auth(db, email, ip, "google", False, "e-mail não verificado")
        return RedirectResponse("/?error=google", status_code=302)

    user = db.scalar(select(User).where(User.google_sub == sub))
    if user is None:
        user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active:
        # cadastro não é aberto: só e-mails convidados por um admin
        _record_auth(db, email, ip, "google", False, "e-mail não convidado")
        return RedirectResponse("/?error=nao_convidado", status_code=302)

    if not user.google_sub:
        user.google_sub = sub
        if not user.name and claims.get("name"):
            user.name = str(claims["name"])[:120]
        db.commit()

    _record_auth(db, email, ip, "google", True)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(OAUTH_COOKIE, path="/api/auth")
    _issue_session(db, user, response)
    return response
