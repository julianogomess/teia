"""Seed do banco: organizações TeIA + ONG de exemplo e usuário admin.

Uso (a partir da pasta server/):
  py -m app.seed            # organizações + admin
  py -m app.seed --demo     # também cria dois usuários member de demonstração

Credenciais do admin vêm de TEIA_ADMIN_EMAIL / TEIA_ADMIN_PASSWORD no .env.
Sem TEIA_ADMIN_PASSWORD, gera uma senha aleatória e a imprime uma única vez.
"""

import secrets
import sys

from sqlalchemy import select

from .config import settings
from .database import Base, SessionLocal, engine
from .models import Organization, User
from .security import hash_password

ORGS = [
    {
        "slug": "teia",
        "name": "TeIA",
        "description": "identidade de marca, princípios e custos de IA da TeIA",
        "context_dir": "context",
        "api_key_env": "ANTHROPIC_API_KEY_TEIA",
    },
    {
        "slug": "ong",
        "name": "Instituto Raízes do Amanhã",
        "description": "documentos institucionais da ONG (missão, projetos, FAQ de doadores)",
        "context_dir": "examples-ong",
        "api_key_env": "ANTHROPIC_API_KEY_ONG",
    },
]

DEMO_USERS = [
    {"email": "teia@teia.org.br", "name": "Equipe TeIA", "org": "teia", "password": "teia1234"},
    {"email": "ong@raizes.org.br", "name": "Equipe ONG", "org": "ong", "password": "ong12345"},
]


def main() -> None:
    demo = "--demo" in sys.argv
    Base.metadata.create_all(engine)  # idempotente; convive com alembic
    db = SessionLocal()
    try:
        orgs = {}
        for data in ORGS:
            org = db.scalar(select(Organization).where(Organization.slug == data["slug"]))
            if org is None:
                org = Organization(**data)
                db.add(org)
                db.flush()
                print(f"organização criada: {data['slug']}")
            orgs[data["slug"]] = org

        admin_email = settings.admin_email.strip().lower()
        if db.scalar(select(User).where(User.email == admin_email)) is None:
            password = settings.admin_password or secrets.token_urlsafe(12)
            db.add(
                User(
                    email=admin_email,
                    name="Administração TeIA",
                    role="superadmin",  # equipe TeIA: visão e gestão globais
                    organization_id=orgs["teia"].id,
                    password_hash=hash_password(password),
                )
            )
            print(f"admin criado: {admin_email}")
            if not settings.admin_password:
                print(f"  senha gerada (guarde agora, não será mostrada de novo): {password}")

        if demo:
            for data in DEMO_USERS:
                if db.scalar(select(User).where(User.email == data["email"])) is None:
                    db.add(
                        User(
                            email=data["email"],
                            name=data["name"],
                            role="member",
                            organization_id=orgs[data["org"]].id,
                            password_hash=hash_password(data["password"]),
                        )
                    )
                    print(f"usuário demo criado: {data['email']} / {data['password']}")

        db.commit()
        print("seed concluído.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
