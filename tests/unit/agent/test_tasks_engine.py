from __future__ import annotations

from app.agent.state import TaskEngine
from app.agent.task import TaskStatus
from app.core.events import EventBus, EventType


def test_engine_start_creates_running_task():
    engine = TaskEngine()
    task = engine.start("Abrir o navegador")
    assert task.status is TaskStatus.running
    assert task.goal == "Abrir o navegador"
    assert engine.current() is task


def test_engine_emits_task_created_event():
    bus = EventBus()
    engine = TaskEngine(event_bus=bus)
    received: list = []
    bus.subscribe(EventType.task_created, received.append)
    task = engine.start("Criar arquivo")
    assert received and received[0].payload["goal"] == "Criar arquivo"
    assert received[0].payload["task_id"] == task.id


def test_engine_step_lifecycle_counts_completed_and_failed():
    engine = TaskEngine()
    task = engine.start("Mover janela")
    step = engine.add_step(task.id, "localizar janela")
    engine.complete_step(task.id, step)
    step2 = engine.add_step(task.id, "arrastar")
    engine.fail_step(task.id, step2)
    assert task.completed_steps == 1
    assert task.failed_steps == 1
    assert step.status == "completed"
    assert step2.status == "failed"


def test_engine_complete_and_fail_status():
    engine = TaskEngine()
    task = engine.start("go")
    engine.complete(task.id, {"ok": True})
    assert task.status is TaskStatus.completed
    assert task.result == {"ok": True}
    assert engine.current() is None

    task2 = engine.start("go2")
    engine.fail(task2.id, "deu ruim")
    assert task2.status is TaskStatus.failed
    assert task2.error == "deu ruim"


def test_engine_cancel_sets_token():
    engine = TaskEngine()
    task = engine.start("go")
    task.cancel_token()
    engine.cancel(task.id)
    assert task.is_cancellation_requested()
    assert task.status is TaskStatus.cancelled


def test_engine_cancel_current():
    engine = TaskEngine()
    task = engine.start("go")
    engine.cancel_current()
    assert task.status is TaskStatus.cancelled
    assert engine.cancel_current() is None


def test_engine_waiting_and_resumed():
    engine = TaskEngine()
    task = engine.start("go")
    engine.waiting(task.id, "confirmation")
    assert task.status is TaskStatus.waiting_confirmation
    engine.resumed(task.id)
    assert task.status is TaskStatus.running


def test_engine_bump_iteration_and_recent():
    engine = TaskEngine()
    task = engine.start("repetitivo")
    engine.bump_iteration(task.id)
    engine.bump_iteration(task.id)
    assert task.iterations == 2
    assert engine.recent(limit=1)[0].id == task.id


def test_engine_missing_task_raises():
    engine = TaskEngine()
    try:
        engine.complete("nao-existe")
    except KeyError:
        assert True
    else:
        raise AssertionError("esperava KeyError")
