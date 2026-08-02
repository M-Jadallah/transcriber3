from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import Mock


CLAIM_TOKEN = "11111111-1111-4111-8111-111111111111"


class SessionContext:
    def __enter__(self) -> Mock:
        self.session = Mock()
        return self.session

    def __exit__(self, *_args: object) -> None:
        return None


def _load_dispatcher(monkeypatch):
    db_module = types.ModuleType("app.core.db")
    db_module.SessionLocal = Mock()
    bootstrap_module = types.ModuleType("app.formatting.celery_bootstrap")
    bootstrap_module.celery_app = Mock()
    monkeypatch.setitem(sys.modules, "app.core.db", db_module)
    monkeypatch.setitem(
        sys.modules,
        "app.formatting.celery_bootstrap",
        bootstrap_module,
    )
    sys.modules.pop("app.formatting.outbox_dispatcher", None)
    return importlib.import_module("app.formatting.outbox_dispatcher")


def test_dispatcher_publishes_with_outbox_id_and_marks_published(monkeypatch) -> None:
    dispatcher = _load_dispatcher(monkeypatch)
    publisher = Mock()
    dispatcher.claim_outbox = Mock(
        return_value={
            "id": "event-1",
            "formatting_job_id": "job-1",
            "task_name": "app.formatting.run_job",
            "payload": {"args": ["job-1"], "kwargs": {}, "queue": "formatting"},
            "attempts": 1,
            "claim_token": CLAIM_TOKEN,
        }
    )
    dispatcher.mark_outbox_published = Mock(return_value=True)

    dispatched = dispatcher.dispatch_once(
        session_factory=SessionContext,
        publisher=publisher,
    )

    assert dispatched is True
    publisher.send_task.assert_called_once_with(
        "app.formatting.run_job",
        args=["job-1"],
        kwargs={},
        queue="formatting",
        task_id="event-1",
    )
    dispatcher.mark_outbox_published.assert_called_once()
    assert dispatcher.mark_outbox_published.call_args.args[2] == CLAIM_TOKEN


def test_dispatcher_sanitizes_failure_and_applies_capped_backoff(monkeypatch) -> None:
    dispatcher = _load_dispatcher(monkeypatch)
    publisher = Mock()
    publisher.send_task.side_effect = RuntimeError(
        "password=super-secret sk-abcdefghijklmnop"
    )
    dispatcher.claim_outbox = Mock(
        return_value={
            "id": "event-1",
            "formatting_job_id": "job-1",
            "task_name": "app.formatting.run_job",
            "payload": {"args": ["job-1"], "kwargs": {}, "queue": "formatting"},
            "attempts": 9,
            "claim_token": CLAIM_TOKEN,
        }
    )
    dispatcher.release_outbox = Mock(return_value=True)

    dispatched = dispatcher.dispatch_once(
        session_factory=SessionContext,
        publisher=publisher,
        backoff_base_seconds=2,
        backoff_cap_seconds=60,
    )

    assert dispatched is True
    call = dispatcher.release_outbox.call_args
    assert call.kwargs["backoff_seconds"] == 60
    assert call.args[2] == CLAIM_TOKEN
    assert "super-secret" not in call.kwargs["error"]
    assert "sk-abcdefghijklmnop" not in call.kwargs["error"]
    assert "[REDACTED]" in call.kwargs["error"]


def test_dispatcher_handles_published_task_id_mismatch(monkeypatch, caplog) -> None:
    dispatcher = _load_dispatcher(monkeypatch)
    dispatcher.claim_outbox = Mock(
        return_value={
            "id": "event-1",
            "formatting_job_id": "job-1",
            "task_name": "app.formatting.run_job",
            "payload": {"args": ["job-1"], "kwargs": {}, "queue": "formatting"},
            "attempts": 1,
            "claim_token": CLAIM_TOKEN,
        }
    )
    dispatcher.mark_outbox_published = Mock(return_value=False)

    assert dispatcher.dispatch_once(
        session_factory=SessionContext,
        publisher=Mock(),
    ) is True
    assert "no longer accepts" in caplog.text


def test_dispatcher_terminally_rejects_every_untrusted_envelope_field(monkeypatch) -> None:
    dispatcher = _load_dispatcher(monkeypatch)
    publisher = Mock()
    dispatcher.cancel_invalid_outbox = Mock(return_value=True)
    valid = {
        "id": "event-1",
        "formatting_job_id": "job-1",
        "task_name": "app.formatting.run_job",
        "payload": {"args": ["job-1"], "kwargs": {}, "queue": "formatting"},
        "attempts": 1,
        "claim_token": CLAIM_TOKEN,
    }
    invalid_events = (
        {**valid, "task_name": "app.tasks.delete_everything"},
        {**valid, "payload": {**valid["payload"], "queue": "celery"}},
        {**valid, "payload": {**valid["payload"], "args": ["job-1", "extra"]}},
        {**valid, "payload": {**valid["payload"], "args": ["../job"]}},
        {**valid, "payload": {**valid["payload"], "args": ["job-2"]}},
        {**valid, "payload": {**valid["payload"], "kwargs": {"command": "bad"}}},
        {**valid, "payload": {**valid["payload"], "unexpected": True}},
    )

    for event in invalid_events:
        dispatcher.claim_outbox = Mock(return_value=event)
        assert dispatcher.dispatch_once(
            session_factory=SessionContext,
            publisher=publisher,
        ) is True

    publisher.send_task.assert_not_called()
    assert dispatcher.cancel_invalid_outbox.call_count == len(invalid_events)
    for call in dispatcher.cancel_invalid_outbox.call_args_list:
        assert call.args[1] == "event-1"
        assert call.args[2] == CLAIM_TOKEN
        assert "delete_everything" not in call.kwargs["error"]


def test_dispatcher_rejects_missing_payload_defaults_instead_of_publishing(monkeypatch) -> None:
    dispatcher = _load_dispatcher(monkeypatch)
    dispatcher.claim_outbox = Mock(
        return_value={
            "id": "event-1",
            "formatting_job_id": "job-1",
            "task_name": "app.formatting.run_job",
            "payload": {"args": ["job-1"]},
            "claim_token": CLAIM_TOKEN,
        }
    )
    dispatcher.cancel_invalid_outbox = Mock(return_value=True)
    publisher = Mock()

    assert dispatcher.dispatch_once(
        session_factory=SessionContext,
        publisher=publisher,
    ) is True
    publisher.send_task.assert_not_called()
    dispatcher.cancel_invalid_outbox.assert_called_once()
