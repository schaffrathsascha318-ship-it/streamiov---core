"""Command-line entry point for the guarded Streamiov development agent."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai.core.agent import AgentError, DevelopmentAgent
from ai.providers.local_http import ProviderError, provider_from_env
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
    if not args.doctor and not args.task:
        parser.error("provide --task or use --doctor")
    if args.doctor and args.task:
        parser.error("--doctor and --task cannot be used together")
    try:
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
    except (AgentError, ProviderError, OSError, ValueError) as exc:
        print(f"streamiov-agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
