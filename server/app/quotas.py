"""Cotas de uso: por usuário/dia e por tenant/mês (mensagens e custo).

Só eventos com result='ok' contam para a cota — tentativas bloqueadas ou
com erro não consomem o limite do usuário.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Organization, UsageEvent, User


def today_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def month_start() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, 1)


def user_messages_today(db: Session, user_id: int) -> int:
    return db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.user_id == user_id,
            UsageEvent.result == "ok",
            UsageEvent.created_at >= today_start(),
        )
    ) or 0


def org_messages_month(db: Session, org_id: int) -> int:
    return db.scalar(
        select(func.count(UsageEvent.id)).where(
            UsageEvent.organization_id == org_id,
            UsageEvent.result == "ok",
            UsageEvent.created_at >= month_start(),
        )
    ) or 0


def org_cost_month(db: Session, org_id: int) -> float:
    return float(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0)).where(
                UsageEvent.organization_id == org_id,
                UsageEvent.result == "ok",
                UsageEvent.created_at >= month_start(),
            )
        )
        or 0.0
    )


def user_daily_limit(user: User) -> int:
    return user.daily_message_limit or settings.default_user_daily_messages


def org_monthly_message_limit(org: Organization) -> int:
    return org.monthly_message_limit or settings.default_org_monthly_messages


def org_monthly_cost_limit(org: Organization) -> float:
    return org.monthly_cost_limit_usd or settings.default_org_monthly_cost_usd


def check_quotas(db: Session, user: User, org: Organization) -> Optional[str]:
    """Devolve a mensagem de erro se alguma cota estourou; None se está tudo ok."""
    if user_messages_today(db, user.id) >= user_daily_limit(user):
        return (
            "Você atingiu sua cota diária de mensagens. "
            "Ela renova à meia-noite (UTC); se precisar de mais, fale com um administrador."
        )
    if org_messages_month(db, org.id) >= org_monthly_message_limit(org):
        return (
            "A organização atingiu a cota mensal de mensagens. "
            "Um administrador pode ajustar o limite no painel."
        )
    if org_cost_month(db, org.id) >= org_monthly_cost_limit(org):
        return (
            "A organização atingiu o teto mensal de custo de IA. "
            "Um administrador pode ajustar o limite no painel."
        )
    return None
