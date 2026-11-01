"""Command-line entry point for the guarded Streamiov development agent."""
from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import sys
import threading
import uuid
from pathlib import Path

from ai.core.agent import AgentError, DevelopmentAgent
from ai.providers.local_http import ProviderError, provider_from_env
from ai.runtime.task_queue import SpecialistTaskQueue, SpecialistWorker, TaskQueueError
from ai.runtime.worker_service import run_worker_loop
from ai.core.orchestrator import SpecialistTask
from ai.core.planner import PlannerError, SpecialistPlanner
from ai.specialists import specialist_names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai",
        description="Run Streamiov's bounded local development agent.",
    )
    parser.add_argument(
        "--task",
        help="A focused development task (maximum 8000 characters).",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check whether the configured local model server and model are ready.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project workspace root (default: current directory).",
    )
    parser.add_argument(
        "--specialist",
        choices=specialist_names(),
        default="code",
        help="Select the least-privilege STREAMIOV AI specialist role (default: code).",
    )
    parser.add_argument("--queue-db", help="SQLite path for the persistent specialist task queue.")
    queue_mode = parser.add_mutually_exclusive_group()
    queue_mode.add_argument("--enqueue", action="store_true", help="Queue --task for the selected specialist instead of running immediately.")
    queue_mode.add_argument("--plan-and-enqueue", action="store_true", help="Ask Core AI to split --task across specialists and persist the validated plan.")
    queue_mode.add_argument("--worker-once", action="store_true", help="Claim and execute at most one queued specialist task, then exit.")
    queue_mode.add_argument("--worker-loop", action="store_true", help="Run a supervised worker until SIGINT/SIGTERM or --max-tasks.")
    parser.add_argument("--poll-seconds", type=int, default=5, help="Idle polling interval for --worker-loop (1–60 seconds).")
    parser.add_argument("--max-tasks", type=int, default=0, help="Stop --worker-loop after this many tasks; 0 means run until stopped.")
    parser.add_argument("--worker-id", default="local-worker", help="Worker identity used for queue leases.")
    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum model/tool turns (1–30, default: 12).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.enqueue:
        if not args.task or not args.queue_db or args.doctor:
            parser.error("--enqueue requires --task and --queue-db and cannot be combined with --doctor")
    elif args.plan_and_enqueue:
        if not args.task or not args.queue_db or args.doctor:
            parser.error("--plan-and-enqueue requires --task and --queue-db and cannot be combined with --doctor")
    elif args.worker_once or args.worker_loop:
        mode = "--worker-loop" if args.worker_loop else "--worker-once"
        if not args.queue_db or args.task or args.doctor:
            parser.error(f"{mode} requires --queue-db and cannot be combined with --task or --doctor")
        if not 1 <= args.max_steps <= 30:
            parser.error("--max-steps must be between 1 and 30")
        if args.worker_loop and not 1 <= args.poll_seconds <= 60:
            parser.error("--poll-seconds must be between 1 and 60")
        if args.worker_loop and args.max_tasks < 0:
            parser.error("--max-tasks must be zero or greater")
    elif not args.doctor and not args.task:
        parser.error("provide --task, use --doctor, or select a queue mode")
    if args.doctor and args.task:
        parser.error("--doctor and --task cannot be used together")
    try:
        if args.plan_and_enqueue:
            provider = provider_from_env()
            tasks = SpecialistPlanner(provider).plan(args.task)
            queue = SpecialistTaskQueue(args.queue_db)
            queue.enqueue_plan(tasks)
            print(json.dumps({"status": "queued", "tasks": [{"task_id": task.task_id, "specialist": task.specialist, "depends_on": list(task.depends_on)} for task in tasks]}, ensure_ascii=False))
            return 0
        if args.enqueue:
            queue = SpecialistTaskQueue(args.queue_db)
            task_id = uuid.uuid4().hex
            queue.enqueue_plan([SpecialistTask(task_id, args.specialist, args.task)])
            print(json.dumps({"task_id": task_id, "specialist": args.specialist, "status": "queued"}, ensure_ascii=False))
            return 0
        if args.worker_once:
            queue = SpecialistTaskQueue(args.queue_db)
            worker = SpecialistWorker(
                queue,
                args.worker_id,
                lambda role: DevelopmentAgent(
                    provider=provider_from_env(),
                    project_root=Path(args.project_root),
                    max_steps=args.max_steps,
                    specialist=role,
                ),
            )
            execution = worker.run_once()
            if execution is None:
                print(json.dumps({"status": "idle"}, ensure_ascii=False))
                return 0
            print(json.dumps({
                "task_id": execution.task_id,
                "status": execution.status,
                "result": execution.result,
                "error": execution.error,
            }, ensure_ascii=False))
            return 0 if execution.status == "succeeded" else 1
        if args.worker_loop:
            queue = SpecialistTaskQueue(args.queue_db)
            worker = SpecialistWorker(
                queue,
                args.worker_id,
                lambda role: DevelopmentAgent(
                    provider=provider_from_env(),
                    project_root=Path(args.project_root),
                    max_steps=args.max_steps,
                    specialist=role,
                ),
            )
            stop_event = threading.Event()
            def request_stop(_signum, _frame):
                stop_event.set()
            watched_signals = (signal.SIGINT, signal.SIGTERM)
            previous_handlers = {item: signal.getsignal(item) for item in watched_signals}
            try:
                for item in watched_signals:
                    signal.signal(item, request_stop)
                return run_worker_loop(
                    worker,
                    stop_event,
                    poll_seconds=args.poll_seconds,
                    max_tasks=args.max_tasks,
                )
            finally:
                for item, handler in previous_handlers.items():
                    signal.signal(item, handler)
        provider = provider_from_env()
        if args.doctor:
            result = provider.check_ready()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ready"] else 3
        agent = DevelopmentAgent(
            provider=provider,
            project_root=Path(args.project_root),
            max_steps=args.max_steps,
            specialist=args.specialist,
        )
        print(agent.run(args.task))
        return 0
    except (AgentError, PlannerError, ProviderError, TaskQueueError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"streamiov-agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
