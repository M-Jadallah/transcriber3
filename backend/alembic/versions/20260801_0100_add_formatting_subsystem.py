"""Add the optional AI formatting subsystem.

Revision ID: 20260801_0100
Revises: 20260701_0001
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260801_0100"
down_revision = "20260701_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "formatting_skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("archive_path", sa.Text(), nullable=False),
        sa.Column("extracted_path", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_formatting_skills_slug", "formatting_skills", ["slug"])

    op.create_table(
        "formatting_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "default_model",
            sa.String(200),
            nullable=False,
            server_default="openai/gpt-5.6-sol",
        ),
        sa.Column(
            "default_reasoning",
            sa.String(16),
            nullable=False,
            server_default="high",
        ),
        sa.Column(
            "default_skill_id",
            sa.String(36),
            sa.ForeignKey("formatting_skills.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "default_reasoning IN ('low', 'medium', 'high', 'xhigh')",
            name="ck_formatting_settings_reasoning",
        ),
    )
    op.execute("INSERT INTO formatting_settings (id) VALUES (1) ON CONFLICT DO NOTHING")

    op.create_table(
        "formatting_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_job_id", sa.String(100), nullable=False),
        sa.Column(
            "skill_id",
            sa.String(36),
            sa.ForeignKey("formatting_skills.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("skill_name_snapshot", sa.String(128), nullable=False),
        sa.Column("skill_sha256_snapshot", sa.String(64), nullable=False),
        sa.Column("model_snapshot", sa.String(200), nullable=False),
        sa.Column("reasoning_snapshot", sa.String(16), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("execution_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(100), nullable=True),
        sa.Column("worker_name", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reasoning_snapshot IN ('low', 'medium', 'high', 'xhigh')",
            name="ck_formatting_jobs_reasoning",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_formatting_jobs_status",
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_formatting_jobs_progress"),
        sa.CheckConstraint(
            "execution_generation >= 0",
            name="ck_formatting_jobs_execution_generation",
        ),
        sa.UniqueConstraint(
            "source_job_id",
            "attempt_number",
            name="uq_formatting_jobs_source_attempt",
        ),
    )
    op.create_index(
        "ix_formatting_jobs_source",
        "formatting_jobs",
        ["source_job_id", "created_at"],
    )
    op.create_index(
        "ix_formatting_jobs_status",
        "formatting_jobs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_formatting_jobs_recovery",
        "formatting_jobs",
        ["status", "lease_expires_at", "updated_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_formatting_jobs_queued_reconcile",
        "formatting_jobs",
        ["updated_at", "created_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    # The source FK is intentionally deferred because the integration target
    # owns the original jobs table and identifier type.
    op.create_index(
        "uq_formatting_jobs_active_source",
        "formatting_jobs",
        ["source_job_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "formatting_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "formatting_job_id",
            sa.String(36),
            sa.ForeignKey("formatting_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_name", sa.String(200), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'published', 'cancelled')",
            name="ck_formatting_outbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_formatting_outbox_attempts"),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_formatting_outbox_payload_object",
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND locked_at IS NOT NULL AND claim_token IS NOT NULL) "
            "OR (status <> 'processing' AND locked_at IS NULL AND claim_token IS NULL)",
            name="ck_formatting_outbox_processing_lock",
        ),
        sa.CheckConstraint(
            "claim_token IS NULL OR claim_token ~* "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'",
            name="ck_formatting_outbox_claim_token_uuid",
        ),
        sa.CheckConstraint(
            "status <> 'published' OR published_at IS NOT NULL",
            name="ck_formatting_outbox_published_at",
        ),
    )
    op.create_index(
        "ix_formatting_outbox_dispatch",
        "formatting_outbox",
        ["status", "available_at", "locked_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_index(
        "uq_formatting_outbox_claim_token",
        "formatting_outbox",
        ["claim_token"],
        unique=True,
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.create_table(
        "formatting_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "formatting_job_id",
            sa.String(36),
            sa.ForeignKey("formatting_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_formatting_artifacts_job",
        "formatting_artifacts",
        ["formatting_job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_formatting_artifacts_job", table_name="formatting_artifacts")
    op.drop_table("formatting_artifacts")
    op.drop_index("uq_formatting_outbox_claim_token", table_name="formatting_outbox")
    op.drop_index("ix_formatting_outbox_dispatch", table_name="formatting_outbox")
    op.drop_table("formatting_outbox")
    op.drop_index("uq_formatting_jobs_active_source", table_name="formatting_jobs")
    op.drop_index("ix_formatting_jobs_queued_reconcile", table_name="formatting_jobs")
    op.drop_index("ix_formatting_jobs_recovery", table_name="formatting_jobs")
    op.drop_index("ix_formatting_jobs_status", table_name="formatting_jobs")
    op.drop_index("ix_formatting_jobs_source", table_name="formatting_jobs")
    op.drop_table("formatting_jobs")
    op.drop_table("formatting_settings")
    op.drop_index("ix_formatting_skills_slug", table_name="formatting_skills")
    op.drop_table("formatting_skills")
