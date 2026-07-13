"""base de conhecimento: documents, chunks, tags, jobs

Revision ID: a1f2c3d4e5f6
Revises: cb9d6d7244b1
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "a1f2c3d4e5f6"
down_revision = "cb9d6d7244b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("ext", sa.String(10), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, index=True),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending", index=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("embedding", sa.LargeBinary, nullable=True),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer,
                  sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("path", sa.String(255), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("source", sa.String(20), nullable=False, server_default="admin"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("organization_id", "path"),
    )
    op.create_table(
        "document_tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("tag_id", sa.Integer,
                  sa.ForeignKey("tags.id"), nullable=False, index=True),
        sa.UniqueConstraint("document_id", "tag_id"),
    )
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer,
                  sa.ForeignKey("documents.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending", index=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingest_jobs")
    op.drop_table("document_tags")
    op.drop_table("tags")
    op.drop_table("document_chunks")
    op.drop_table("documents")
