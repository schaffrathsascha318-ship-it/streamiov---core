"""Bounded parallel execution for the persistent specialist queue."""
from __future__ import annotations

import json
import threading
from typing import Callable


def run_worker_pool(
    worker_factory: Callable[[str], object],
    stop_event: threading.Event,
    *,
    workers: int = 2,
    poll_seconds: int = 5,
    max_tasks: int = 0,
    worker_id_prefix: str = "streamiov-worker",
    emit: Callable[[str], None] = print,
) -> int:
    """Run independent queue workers concurrently with a shared task budget.

    The queue remains the source of truth: each worker must use the same durable
    queue instance (or database) and claim tasks using its unique worker ID.
    max_tasks is global across the pool; zero means supervisor-controlled.
    """
    if isinstance(workers, bool) or not isinstance(workers, int) or not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8.")
    if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, int) or not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60.")
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 0:
        raise ValueError("max_tasks must be a non-negative integer.")
    if not isinstance(worker_id_prefix, str) or not worker_id_prefix.strip() or len(worker_id_prefix) > 96:
        raise ValueError("worker_id_prefix must contain 1–96 characters.")

    lock = threading.Lock()
    reserved = 0
    had_failure = False

    def run_one(worker_index: int) -> None:
        nonlocal reserved, had_failure
        worker_id = f"{worker_id_prefix}-{worker_index + 1}"
        worker = worker_factory(worker_id)
        while not stop_event.is_set():
            with lock:
                if max_tasks and reserved >= max_tasks:
                    return
                reserved += 1
            try:
                execution = worker.run_once()
            except Exception as exc:
                with lock:
                    reserved -= 1
                    had_failure = True
                emit(json.dumps({
                    "worker_id": worker_id,
                    "status": "worker_error",
                    "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                }, ensure_ascii=False))
                return
            if execution is None:
                with lock:
                    reserved -= 1
                stop_event.wait(poll_seconds)
                continue
            if execution.status != "succeeded":
                with lock:
                    had_failure = True
            emit(json.dumps({
                "worker_id": worker_id,
                "task_id": execution.task_id,
                "status": execution.status,
                "result": execution.result,
                "error": execution.error,
            }, ensure_ascii=False))
        return

    threads = [
        threading.Thread(target=run_one, args=(index,), name=f"streamiov-worker-{index + 1}")
        for index in range(workers)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return 1 if had_failure else 0
