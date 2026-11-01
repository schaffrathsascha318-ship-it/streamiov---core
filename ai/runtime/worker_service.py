"""Supervised worker loop with cooperative shutdown and bounded polling."""
from __future__ import annotations

import json
import threading
from typing import Callable


def run_worker_loop(worker, stop_event: threading.Event, *, poll_seconds: int = 5, max_tasks: int = 0, emit: Callable[[str], None] = print) -> int:
    """Run until stopped or max_tasks is reached; max_tasks=0 means supervisor-controlled."""
    if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, int) or not 1 <= poll_seconds <= 60:
        raise ValueError("poll_seconds must be between 1 and 60.")
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 0:
        raise ValueError("max_tasks must be a non-negative integer.")
    processed = 0
    had_failure = False
    while not stop_event.is_set() and (max_tasks == 0 or processed < max_tasks):
        execution = worker.run_once()
        if execution is None:
            stop_event.wait(poll_seconds)
            continue
        processed += 1
        if execution.status != "succeeded":
            had_failure = True
        emit(json.dumps({
            "task_id": execution.task_id,
            "status": execution.status,
            "result": execution.result,
            "error": execution.error,
        }, ensure_ascii=False))
    return 1 if had_failure else 0
