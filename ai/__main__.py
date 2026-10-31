"""Command-line entry point for the guarded Streamiov development agent."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai.core.agent import AgentError, DevelopmentAgent
from ai.providers.local_http import ProviderError, provider_from_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai",
        description="Run Streamiov's bounded local development agent.",
    )
    parser.add_argument(
        "--task",
        required=True,
        help="A focused development task (maximum 8000 characters).",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project workspace root (default: current directory).",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=12,
        help="Maximum model/tool turns (1–30, default: 12).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        provider = provider_from_env()
        agent = DevelopmentAgent(
            provider=provider,
            project_root=Path(args.project_root),
            max_steps=args.max_steps,
        )
        print(agent.run(args.task))
        return 0
    except (AgentError, ProviderError, OSError, ValueError) as exc:
        print(f"streamiov-agent: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
