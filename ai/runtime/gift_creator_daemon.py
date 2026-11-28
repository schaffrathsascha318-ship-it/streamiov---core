"""Long-running Gift Creator scheduler + existing specialist queue worker.

Run with:
python -m ai.runtime.gift_creator_daemon --queue-db data/db/gift-creator-queue.sqlite3 \
  --schedule-db data/db/gift-creator-schedule.sqlite3 --project-root .
"""
from __future__ import annotations

import argparse
import json
import signal
import threading
from pathlib import Path

from ai.core.agent import DevelopmentAgent
from ai.providers.local_http import provider_from_env
from ai.runtime.gift_creator_scheduler import GiftCreatorScheduler
from ai.runtime.learning_store import VerifiedLearningStore
from ai.runtime.task_queue import SpecialistTaskQueue, SpecialistWorker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Streamiov's continuous Gift Creator AI scheduler.")
    parser.add_argument("--queue-db", required=True, help="Persistent SQLite specialist queue.")
    parser.add_argument("--schedule-db", required=True, help="Persistent SQLite Gift Creator schedule state.")
    parser.add_argument("--project-root", default=".", help="Streamiov repository/workspace root.")
    parser.add_argument("--poll-seconds", type=int, default=30, help="Idle delay between scheduler/worker passes (1–300).")
    parser.add_argument("--max-steps", type=int, default=12, help="Agent tool turns per task (1–30).")
    parser.add_argument("--worker-id", default="gift-creator-worker", help="Unique worker lease identity.")
    parser.add_argument("--learning-db", help="Optional verified-learning SQLite database.")
    parser.add_argument("--once", action="store_true", help="Schedule due work and process at most one task, then exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.poll_seconds <= 300:
        raise SystemExit("--poll-seconds must be between 1 and 300")
    if not 1 <= args.max_steps <= 30:
        raise SystemExit("--max-steps must be between 1 and 30")

    root = Path(args.project_root).resolve()
    queue = SpecialistTaskQueue(args.queue_db)
    scheduler = GiftCreatorScheduler(queue, args.schedule_db)
    learning = VerifiedLearningStore(args.learning_db) if args.learning_db else None
    stop = threading.Event()

    def request_stop(_signum, _frame):
        stop.set()

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, request_stop)

    worker = SpecialistWorker(
        queue,
        args.worker_id,
        lambda role: DevelopmentAgent(
            provider=provider_from_env(),
            project_root=root,
            max_steps=args.max_steps,
            specialist=role,
            learning_store=learning,
        ),
    )
    exit_code = 0
    try:
        while not stop.is_set():
            scheduled = scheduler.schedule_due()
            execution = worker.run_once()
            print(json.dumps({
                "scheduled": scheduled["scheduled"],
                "seasonal_windows": scheduled["seasonal_windows"],
                "execution": None if execution is None else {
                    "task_id": execution.task_id,
                    "status": execution.status,
                    "error": execution.error,
                },
            }, ensure_ascii=False), flush=True)
            if execution is not None and execution.status not in {"succeeded"}:
                exit_code = 1
            if args.once:
                break
            if execution is None:
                stop.wait(args.poll_seconds)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
