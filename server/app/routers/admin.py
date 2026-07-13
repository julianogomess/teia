"""Rotas administrativas: métricas do painel e gestão de usuários/cotas.

Todas exigem papel 'admin' (require_admin) — a checagem é no servidor,
o frontend só reflete o resultado.
"""

import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import require_admin
from ..models import ROLES, AuthEvent, Organization, UsageEvent, User
from ..quotas import (
    month_start,
    org_cost_month,
    org_messages_month,
    org_monthly_cost_limit,
    org_monthly_message_limit,
    today_start,
    user_daily_limit,
    user_messages_today,
)
from ..security import hash_password

router = APIRouter(
    prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)

_PROCESS_START = time.monotonic()


# ------------------------------------------------------------------- métricas
@router.get("/metrics")
def metrics(days: int = 14, db: Session = Depends(get_db)):
    days = max(1, min(days, 90))
    now = datetime.utcnow()
    day0 = today_start()
    last_24h = now - timedelta(hours=24)
    series_start = day0 - timedelta(days=days - 1)

    # ---- cartões ----------------------------------------------------------
    messages_today = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.result == "ok", UsageEvent.created_at >= day0
        )
    ) or 0
    cost_month = float(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0)).where(
                UsageEvent.result == "ok", UsageEvent.created_at >= month_start()
            )
        ) or 0.0
    )
    active_users_today = db.scalar(
        select(func.count(func.distinct(UsageEvent.user_id))).where(
            UsageEvent.result == "ok", UsageEvent.created_at >= day0
        )
    ) or 0
    avg_latency = db.scalar(
        select(func.avg(UsageEvent.latency_ms)).where(
            UsageEvent.result == "ok", UsageEvent.created_at >= last_24h
        )
    )
    total_24h = db.scalar(
        select(func.count(UsageEvent.id)).where(UsageEvent.created_at >= last_24h)
    ) or 0
    errors_24h = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.result == "error", UsageEvent.created_at >= last_24h
        )
    ) or 0
    blocked_24h = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.result.in_(["rate_limited", "quota_exceeded"]),
            UsageEvent.created_at >= last_24h,
        )
    ) or 0

    # ---- série por dia (agregada em Python: portável SQLite/Postgres) -----
    rows = db.execute(
        select(UsageEvent.created_at, UsageEvent.cost_usd).where(
            UsageEvent.result == "ok", UsageEvent.created_at >= series_start
        )
    ).all()
    per_day = {}
    for created_at, cost in rows:
        key = created_at.date().isoformat()
        bucket = per_day.setdefault(key, {"messages": 0, "cost_usd": 0.0})
        bucket["messages"] += 1
        bucket["cost_usd"] += cost or 0.0
    series = []
    for i in range(days):
        d = (series_start + timedelta(days=i)).date().isoformat()
        bucket = per_day.get(d, {"messages": 0, "cost_usd": 0.0})
        series.append(
            {"date": d, "messages": bucket["messages"],
             "cost_usd": round(bucket["cost_usd"], 4)}
        )

    # ---- uso e cota por organização ----------------------------------------
    per_org = []
    for org in db.scalars(select(Organization).order_by(Organization.name)).all():
        per_org.append(
            {
                "slug": org.slug,
                "name": org.name,
                "messages_month": org_messages_month(db, org.id),
                "message_limit": org_monthly_message_limit(org),
                "cost_month_usd": round(org_cost_month(db, org.id), 4),
                "cost_limit_usd": org_monthly_cost_limit(org),
            }
        )

    # ---- top usuários do mês ------------------------------------------------
    top_rows = db.execute(
        select(
            UsageEvent.user_id,
            func.count(UsageEvent.id).label("msgs"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0.0).label("cost"),
        )
        .where(UsageEvent.result == "ok", UsageEvent.created_at >= month_start())
        .group_by(UsageEvent.user_id)
        .order_by(func.count(UsageEvent.id).desc())
        .limit(10)
    ).all()
    top_users = []
    for user_id, msgs, cost in top_rows:
        user = db.get(User, user_id) if user_id else None
        if user is None:
            continue
        top_users.append(
            {
                "email": user.email,
                "org": user.organization.name,
                "messages_month": msgs,
                "cost_month_usd": round(float(cost), 4),
                "messages_today": user_messages_today(db, user.id),
                "daily_limit": user_daily_limit(user),
            }
        )

    # ---- segurança ----------------------------------------------------------
    failed_logins_24h = db.scalar(
        select(func.count(AuthEvent.id)).where(
            AuthEvent.success.is_(False), AuthEvent.created_at >= last_24h
        )
    ) or 0
    rate_limited_24h = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.result == "rate_limited", UsageEvent.created_at >= last_24h
        )
    ) or 0
    quota_exceeded_24h = db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.result == "quota_exceeded", UsageEvent.created_at >= last_24h
        )
    ) or 0
    recent_auth = [
        {
            "email": e.email,
            "ip": e.ip,
            "method": e.method,
            "success": e.success,
            "detail": e.detail,
            "at": e.created_at.isoformat() + "Z",
        }
        for e in db.scalars(
            select(AuthEvent).order_by(AuthEvent.created_at.desc()).limit(20)
        ).all()
    ]
    top_ips = _top_ips(db, last_24h)

    return {
        "generated_at": now.isoformat() + "Z",
        "uptime_seconds": int(time.monotonic() - _PROCESS_START),
        "model": settings.anthropic_model,
        "cards": {
            "messages_today": messages_today,
            "cost_month_usd": round(cost_month, 4),
            "active_users_today": active_users_today,
            "avg_latency_ms_24h": int(avg_latency) if avg_latency else 0,
            "error_rate_24h": round(errors_24h / total_24h, 4) if total_24h else 0.0,
            "blocked_24h": blocked_24h,
        },
        "per_day": series,
        "per_org": per_org,
        "top_users": top_users,
        "security": {
            "failed_logins_24h": failed_logins_24h,
            "rate_limited_24h": rate_limited_24h,
            "quota_exceeded_24h": quota_exceeded_24h,
            "recent_auth": recent_auth,
            "top_ips_24h": top_ips,
        },
    }


def _top_ips(db: Session, since: datetime):
    rows = db.execute(
        select(AuthEvent.ip, AuthEvent.success).where(AuthEvent.created_at >= since)
    ).all()
    counts = {}
    for ip, success in rows:
        bucket = counts.setdefault(ip, {"attempts": 0, "failures": 0})
        bucket["attempts"] += 1
        if not success:
            bucket["failures"] += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1]["attempts"], reverse=True)[:10]
    return [{"ip": ip, **data} for ip, data in ranked]


# ------------------------------------------------------------------- usuários
def _user_row(db: Session, user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "is_active": user.is_active,
        "org_slug": user.organization.slug,
        "org_name": user.organization.name,
        "has_google": bool(user.google_sub),
        "messages_today": user_messages_today(db, user.id),
        "daily_limit": user_daily_limit(user),
        "created_at": user.created_at.isoformat() + "Z",
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.email)).all()
    return {"users": [_user_row(db, u) for u in users]}


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: Optional[str] = None
    role: str = "member"
    org_slug: str
    # opcional: sem senha, a conta só consegue entrar com Google
    password: Optional[str] = Field(default=None, min_length=8)


@router.post("/users", status_code=201)
def create_user(body: CreateUserRequest, db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise HTTPException(422, f"Papel inválido. Use um de: {', '.join(ROLES)}.")
    org = db.scalar(select(Organization).where(Organization.slug == body.org_slug))
    if org is None:
        raise HTTPException(404, "Organização não encontrada.")
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Já existe um usuário com esse e-mail.")
    user = User(
        email=email,
        name=body.name,
        role=body.role,
        organization_id=org.id,
        password_hash=hash_password(body.password) if body.password else None,
    )
    db.add(user)
    db.commit()
    return _user_row(db, user)


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: Optional[bool] = None
    role: Optional[str] = None
    daily_message_limit: Optional[int] = Field(default=None, ge=0)
    password: Optional[str] = Field(default=None, min_length=8)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UpdateUserRequest,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuário não encontrado.")
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, f"Papel inválido. Use um de: {', '.join(ROLES)}.")
        if user.id == admin.id and body.role != "admin":
            raise HTTPException(422, "Você não pode rebaixar a própria conta.")
        user.role = body.role
    if body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(422, "Você não pode bloquear a própria conta.")
        user.is_active = body.is_active
    if body.daily_message_limit is not None:
        user.daily_message_limit = body.daily_message_limit or None
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    return _user_row(db, user)


# -------------------------------------------------------------- organizações
@router.get("/organizations")
def list_organizations(db: Session = Depends(get_db)):
    orgs = db.scalars(select(Organization).order_by(Organization.name)).all()
    return {
        "organizations": [
            {
                "slug": o.slug,
                "name": o.name,
                "context_dir": o.context_dir,
                "monthly_message_limit": org_monthly_message_limit(o),
                "monthly_cost_limit_usd": org_monthly_cost_limit(o),
            }
            for o in orgs
        ]
    }


class UpdateOrgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_message_limit: Optional[int] = Field(default=None, ge=0)
    monthly_cost_limit_usd: Optional[float] = Field(default=None, ge=0)


@router.patch("/organizations/{slug}")
def update_organization(slug: str, body: UpdateOrgRequest, db: Session = Depends(get_db)):
    org = db.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        raise HTTPException(404, "Organização não encontrada.")
    if body.monthly_message_limit is not None:
        org.monthly_message_limit = body.monthly_message_limit or None
    if body.monthly_cost_limit_usd is not None:
        org.monthly_cost_limit_usd = body.monthly_cost_limit_usd or None
    db.commit()
    return {
        "slug": org.slug,
        "monthly_message_limit": org_monthly_message_limit(org),
        "monthly_cost_limit_usd": org_monthly_cost_limit(org),
    }
