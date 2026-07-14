"""admins da TeIA viram superadmin

Migração de dados: com o papel 'admin' passando a ser escopado ao próprio
tenant, os admins existentes da organização TeIA são promovidos a
'superadmin' para manterem a visão e gestão globais.

Revision ID: 920f315de02e
Revises: a1f2c3d4e5f6
Create Date: 2026-07-13

"""
from alembic import op


revision = '920f315de02e'
down_revision = 'a1f2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE users SET role = 'superadmin'
        WHERE role = 'admin'
          AND organization_id IN (SELECT id FROM organizations WHERE slug = 'teia')
        """
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'superadmin'")
