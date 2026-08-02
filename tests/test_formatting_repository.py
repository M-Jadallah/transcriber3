from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock

try:
    import sqlalchemy  # noqa: F401
except ModuleNotFoundError:
    sqlalchemy_module = types.ModuleType("sqlalchemy")
    sqlalchemy_orm_module = types.ModuleType("sqlalchemy.orm")

    class TextStatement(str):
        def bindparams(self, *_args: object, **_kwargs: object) -> "TextStatement":
            return self

    sqlalchemy_module.bindparam = lambda *_args, **_kwargs: object()
    sqlalchemy_module.text = TextStatement
    sqlalchemy_orm_module.Session = object
    sys.modules["sqlalchemy"] = sqlalchemy_module
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_module

from app.formatting.repository import (
    ActiveFormattingJobError,
    active_running_execution_keys,
    cancel_invalid_outbox,
    cancel_job,
    claim_outbox,
    claim_job,
    complete_job,
    create_job,
    disable_skill_with_replacement,
    has_active_jobs,
    heartbeat_job,
    mark_outbox_published,
    reconcile_queued_jobs,
    recover_expired_jobs,
    release_outbox,
    update_job,
    update_owned_job,
)


class Row:
    def __init__(self, **values: object) -> None:
        self._mapping = values


class Result:
    def __init__(
        self,
        row: Row | None = None,
        *,
        rowcount: int = 0,
        scalar: object = None,
        rows: list[Row] | None = None,
    ) -> None:
        self._row = row
        self.rowcount = rowcount
        self._scalar = scalar
        self._rows = rows or []

    def first(self) -> Row | None:
        return self._row

    def scalar_one(self) -> object:
        return self._scalar

    def all(self) -> list[Row]:
        return self._rows


class FormattingRepositoryTests(unittest.TestCase):
    def test_disabling_default_selects_replacement_before_one_commit(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(default_skill_id="skill-1")),
            Result(Row(id="skill-2")),
            Result(rowcount=1),
            Result(rowcount=1),
        ]

        replacement = disable_skill_with_replacement(db, "skill-1")

        self.assertEqual(replacement, "skill-2")
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("FOR UPDATE", statements[0])
        self.assertIn("id <> :id", statements[1])
        self.assertIn("default_skill_id = :replacement", statements[2])
        self.assertIn("is_enabled = FALSE", statements[3])

    def test_duplicate_active_job_is_rejected_under_source_lock(self) -> None:
        db = Mock()
        db.execute.side_effect = [Result(), Result(), Result(Row(id="active-job"))]

        with self.assertRaises(ActiveFormattingJobError) as raised:
            create_job(
                db,
                source_job_id="source-1",
                skill={"id": "skill", "name": "Skill", "sha256": "abc"},
                model="provider/model",
                reasoning="high",
                input_hash="hash",
                requested_by="admin",
            )

        self.assertEqual(raised.exception.job_id, "active-job")
        db.rollback.assert_called_once()
        db.commit.assert_not_called()

    def test_job_and_outbox_are_inserted_before_one_commit(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(),
            Result(),
            Result(),
            Result(scalar=2),
            Result(rowcount=1),
            Result(rowcount=1),
            Result(Row(id="job-1", status="queued", attempt_number=2)),
        ]

        created = create_job(
            db,
            job_id="job-1",
            source_job_id="source-1",
            skill={"id": "skill", "name": "Skill", "sha256": "abc"},
            model="provider/model",
            reasoning="high",
            input_hash="hash",
            requested_by="admin",
        )

        self.assertEqual(created["status"], "queued")
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("INSERT INTO formatting_jobs", statements[4])
        self.assertIn("INSERT INTO formatting_outbox", statements[5])
        outbox_parameters = db.execute.call_args_list[5].args[1]
        self.assertEqual(outbox_parameters["job_id"], "job-1")
        self.assertIn('"args": ["job-1"]', outbox_parameters["payload"])

    def test_claim_increments_independent_execution_generation(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(),
            Result(
                Row(
                    id="job-1",
                    status="running",
                    celery_task_id="task-1",
                    execution_generation=4,
                )
            ),
        ]

        claimed = claim_job(
            db,
            "job-1",
            celery_task_id="task-1",
            worker_name="worker",
        )

        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["execution_generation"], 4)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("formatting:auth", statements[0])
        statement = statements[1]
        self.assertIn("status = 'queued'", statement)
        self.assertIn("execution_generation = execution_generation + 1", statement)
        self.assertIn("lease_expires_at <= NOW()", statement)
        self.assertNotIn("celery_task_id = :task_id AND", statement)
        self.assertIn("RETURNING *", statement)

    def test_heartbeat_extends_only_the_current_unexpired_owner(self) -> None:
        db = Mock()
        db.execute.return_value = Result(rowcount=1)

        renewed = heartbeat_job(
            db,
            "job-1",
            execution_generation=4,
            lease_seconds=180,
        )

        self.assertTrue(renewed)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("heartbeat_at = NOW()", statement)
        self.assertIn("execution_generation = :generation", statement)
        self.assertIn("lease_expires_at > NOW()", statement)
        self.assertEqual(db.execute.call_args.args[1]["generation"], 4)

    def test_owned_terminal_update_clears_lease(self) -> None:
        db = Mock()
        db.execute.return_value = Result(rowcount=1)

        changed = update_owned_job(
            db,
            "job-1",
            4,
            status="failed",
            progress=100,
        )

        self.assertTrue(changed)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("lease_expires_at = :lease_expires_at", statement)
        self.assertIn("execution_generation = :generation", statement)

    def test_generic_updates_require_current_running_generation(self) -> None:
        db = Mock()
        db.execute.return_value = Result(rowcount=0)

        changed = update_job(
            db,
            "job-1",
            execution_generation=4,
            progress=90,
        )

        self.assertFalse(changed)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("status = 'running'", statement)
        self.assertIn("execution_generation = :generation", statement)
        self.assertIn("lease_expires_at > NOW()", statement)

    def test_cancellation_only_transitions_active_jobs(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(id="job-1", status="cancelled")),
            Result(rowcount=1),
        ]

        cancelled = cancel_job(db, "job-1")

        self.assertEqual(cancelled["status"], "cancelled")
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("status IN ('queued', 'running')", statements[0])
        self.assertIn("lease_expires_at = NULL", statements[0])
        self.assertIn("RETURNING *", statements[0])
        self.assertIn("UPDATE formatting_outbox", statements[1])
        self.assertIn("'pending', 'processing'", statements[1])
        self.assertEqual(db.commit.call_count, 1)

    def test_completion_locks_job_and_artifacts_in_one_commit(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(id="job-1")),
            Result(rowcount=1),
            Result(rowcount=1),
        ]

        completed = complete_job(db, "job-1", 4, [], "preview")

        self.assertTrue(completed)
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("FOR UPDATE", statements[0])
        self.assertIn("DELETE FROM formatting_artifacts", statements[1])
        self.assertIn("status = 'completed'", statements[2])
        self.assertIn("execution_generation = :generation", statements[0])
        self.assertIn("execution_generation = :generation", statements[2])
        self.assertIn("lease_expires_at = NULL", statements[2])

    def test_logout_guard_holds_shared_auth_lock_and_counts_queued_jobs(self) -> None:
        db = Mock()
        db.execute.side_effect = [Result(), Result(scalar=True)]

        self.assertTrue(has_active_jobs(db))

        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("formatting:auth", statements[0])
        self.assertIn("'queued', 'running'", statements[1])

    def test_active_execution_keys_include_unexpired_and_recent_running_leases(self) -> None:
        db = Mock()
        db.execute.return_value = Result(
            rows=[Row(id="job-1", execution_generation=4)]
        )

        keys = active_running_execution_keys(db, recent_lease_seconds=180)

        self.assertEqual(keys, {"job-1-g4"})
        statement = str(db.execute.call_args.args[0])
        self.assertIn("status = 'running'", statement)
        self.assertIn("execution_generation > 0", statement)
        self.assertIn("lease_expires_at > NOW() -", statement)
        self.assertEqual(
            db.execute.call_args.args[1]["recent_lease_seconds"], 180
        )

    def test_outbox_claim_reclaims_stale_processing_with_skip_locked(self) -> None:
        db = Mock()
        db.execute.return_value = Result(
            Row(id="event-1", status="processing", attempts=3)
        )

        event = claim_outbox(db, stale_seconds=120)

        self.assertEqual(event["attempts"], 3)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("status = 'pending'", statement)
        self.assertIn("status = 'processing'", statement)
        self.assertIn("FOR UPDATE SKIP LOCKED", statement)
        self.assertRegex(statement, r"LIMIT 1\s+FOR UPDATE SKIP LOCKED")
        self.assertIn("attempts = event.attempts + 1", statement)
        self.assertIn("claim_token = :claim_token", statement)
        claim_token = db.execute.call_args.args[1]["claim_token"]
        self.assertRegex(
            claim_token,
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )

    def test_stale_outbox_owner_cannot_mark_reclaimed_event(self) -> None:
        db = Mock()
        db.execute.return_value = Result()

        published = mark_outbox_published(db, "event-1", "stale-claim")

        self.assertFalse(published)
        self.assertEqual(db.rollback.call_count, 1)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("id = :id AND status = 'processing'", statement)
        self.assertIn("claim_token = :claim_token", statement)

    def test_published_outbox_copies_deterministic_task_id_atomically(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(formatting_job_id="job-1")),
            Result(rowcount=1),
        ]

        published = mark_outbox_published(db, "event-1", "claim-1")

        self.assertTrue(published)
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("status = 'published'", statements[0])
        self.assertIn("claim_token = :claim_token", statements[0])
        self.assertIn("claim_token = NULL", statements[0])
        self.assertIn("celery_task_id = :task_id", statements[1])
        self.assertEqual(db.execute.call_args_list[1].args[1]["task_id"], "event-1")

    def test_published_outbox_reports_job_task_id_ownership_mismatch(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(formatting_job_id="job-1")),
            Result(rowcount=0),
        ]

        published = mark_outbox_published(db, "event-1", "claim-1")

        self.assertFalse(published)
        self.assertEqual(db.commit.call_count, 1)

    def test_publish_failure_returns_processing_event_to_pending(self) -> None:
        db = Mock()
        db.execute.return_value = Result(rowcount=1)

        released = release_outbox(
            db,
            "event-1",
            "claim-1",
            error="sanitized",
            backoff_seconds=8,
        )

        self.assertTrue(released)
        statement = str(db.execute.call_args.args[0])
        self.assertIn("status = 'pending'", statement)
        self.assertIn("locked_at = NULL", statement)
        self.assertIn("claim_token = NULL", statement)
        self.assertIn("claim_token = :claim_token", statement)
        self.assertEqual(db.execute.call_args.args[1]["backoff_seconds"], 8)

    def test_invalid_outbox_and_queued_job_are_cancelled_in_one_commit(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(Row(formatting_job_id="job-1")),
            Result(rowcount=1),
        ]

        cancelled = cancel_invalid_outbox(
            db, "event-1", "claim-1", error="safe error"
        )

        self.assertTrue(cancelled)
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("status = 'cancelled'", statements[0])
        self.assertIn("claim_token = :claim_token", statements[0])
        self.assertIn("claim_token = NULL", statements[0])
        self.assertIn("status = 'cancelled'", statements[1])
        self.assertIn("status = 'queued'", statements[1])
        self.assertEqual(
            db.execute.call_args_list[1].args[1]["error"], "safe error"
        )

    def test_expired_running_recovery_queues_and_emits_new_event_in_one_commit(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(rows=[Row(id="job-1")]),
            Result(rowcount=1),
            Result(rowcount=1),
        ]

        recovered = recover_expired_jobs(db, limit=10)

        self.assertEqual(recovered, 1)
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("FOR UPDATE SKIP LOCKED", statements[0])
        self.assertRegex(
            statements[0], r"LIMIT :limit\s+FOR UPDATE SKIP LOCKED"
        )
        self.assertIn("status = 'queued'", statements[0])
        self.assertIn("UPDATE formatting_outbox", statements[1])
        self.assertIn("INSERT INTO formatting_outbox", statements[2])

    def test_old_queued_reconciliation_adds_event_only_without_active_delivery(self) -> None:
        db = Mock()
        db.execute.side_effect = [
            Result(rows=[Row(id="job-1")]),
            Result(rowcount=1),
        ]

        reconciled = reconcile_queued_jobs(db, min_age_seconds=300, limit=10)

        self.assertEqual(reconciled, 1)
        self.assertEqual(db.commit.call_count, 1)
        statements = [str(call.args[0]) for call in db.execute.call_args_list]
        self.assertIn("job.status = 'queued'", statements[0])
        self.assertIn("event.status IN ('pending', 'processing')", statements[0])
        self.assertIn("FOR UPDATE SKIP LOCKED", statements[0])
        self.assertRegex(
            statements[0], r"LIMIT :limit\s+FOR UPDATE SKIP LOCKED"
        )
        self.assertIn("INSERT INTO formatting_outbox", statements[1])


if __name__ == "__main__":
    unittest.main()
