from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260801_0100_add_formatting_subsystem.py"
)


def test_migration_has_outbox_lease_and_active_source_shape() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    ast.parse(source)

    assert 'sa.Column("lease_expires_at"' in source
    assert 'sa.Column("heartbeat_at"' in source
    assert 'sa.Column("execution_generation"' in source
    assert '"execution_generation >= 0"' in source
    assert '"ix_formatting_jobs_recovery"' in source
    assert '"ix_formatting_jobs_queued_reconcile"' in source
    assert '"uq_formatting_jobs_active_source"' in source
    assert 'postgresql_where=sa.text("status IN (\'queued\', \'running\')")' in source
    assert '"formatting_outbox"' in source
    assert 'sa.ForeignKey("formatting_jobs.id", ondelete="CASCADE")' in source
    assert "'pending', 'processing', 'published', 'cancelled'" in source
    assert '"ix_formatting_outbox_dispatch"' in source
    assert 'sa.Column("claim_token", sa.String(36), nullable=True)' in source
    assert '"ck_formatting_outbox_claim_token_uuid"' in source
    assert '"uq_formatting_outbox_claim_token"' in source
    assert "status <> 'processing' AND locked_at IS NULL AND claim_token IS NULL" in source


def test_migration_downgrade_removes_outbox_before_jobs() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade()") :]

    assert downgrade.index('op.drop_table("formatting_outbox")') < downgrade.index(
        'op.drop_table("formatting_jobs")'
    )
    assert downgrade.index('op.drop_index("uq_formatting_outbox_claim_token"') < (
        downgrade.index('op.drop_table("formatting_outbox")')
    )
    assert 'op.drop_index("uq_formatting_jobs_active_source"' in downgrade
    assert 'op.drop_index("ix_formatting_jobs_recovery"' in downgrade
    assert 'op.drop_index("ix_formatting_jobs_queued_reconcile"' in downgrade


def test_outbox_repository_and_dispatcher_use_claim_fence_statically() -> None:
    root = ROOT
    repository = (root / "backend/app/formatting/repository.py").read_text(
        encoding="utf-8"
    )
    dispatcher = (root / "backend/app/formatting/outbox_dispatcher.py").read_text(
        encoding="utf-8"
    )

    for function_name, next_function in (
        ("def mark_outbox_published(", "def cancel_invalid_outbox("),
        ("def cancel_invalid_outbox(", "def release_outbox("),
        ("def release_outbox(", "def complete_job("),
    ):
        section = repository[
            repository.index(function_name) : repository.index(next_function)
        ]
        assert "AND status = 'processing' AND claim_token = :claim_token" in section
        assert "claim_token = NULL" in section

    assert "claim_token = :claim_token" in repository[
        repository.index("def claim_outbox(") : repository.index(
            "def mark_outbox_published("
        )
    ]
    assert "mark_outbox_published(db, outbox_id, claim_token)" in dispatcher
    assert "cancel_invalid_outbox(db, claimed_id, claimed_token" in dispatcher
    assert "outbox_id,\n                claim_token," in dispatcher
