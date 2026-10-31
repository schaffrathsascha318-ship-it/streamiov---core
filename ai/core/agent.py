"""Small tool-using development agent backed by a real local model endpoint."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.providers.base import ModelProvider

SYSTEM = """You are Streamiov's coding agent. Work only on the supplied project task.
You may request exactly one JSON object per response:
{"tool":"read_file","arguments":{"path":"relative/path"}}
{"tool":"write_file","arguments":{"path":"new/relative/path","content":"complete file text"}}
{"tool":"replace_text","arguments":{"path":"ai/file.py","old_text":"one exact existing section","new_text":"its replacement"}}
{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}
{"final":"concise result"}
Never request secrets, environment files, credentials, OAuth data, production actions, arbitrary shell commands, network access, or overwriting files wholesale. Exact-match edits must target one unique section. Paths and tools are enforced independently. Do not claim a test passed unless its output proves it. Return JSON only."""

def _parse_action(content: str):
    """Parse a JSON action, accepting a single optional Markdown JSON fence."""
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)

MAX_MODEL_REPLY_CHARS = 100_000

class AgentError(RuntimeError):
    pass

class DevelopmentAgent:
    def __init__(self, provider: ModelProvider, project_root: str | Path, max_steps: int = 12) -> None:
        if not 1 <= max_steps <= 30:
            raise ValueError("max_steps must be between 1 and 30")
        self.provider = provider
        self.tools = ProjectTools(project_root)
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        if not isinstance(task, str) or not task.strip() or len(task) > 8000:
            raise ValueError("Task must contain 1–8000 characters.")
        messages = [{"role": "user", "content": task.strip()}]
        for _ in range(self.max_steps):
            reply = self.provider.generate(system=SYSTEM, messages=messages)
            if not isinstance(reply.content, str) or len(reply.content) > MAX_MODEL_REPLY_CHARS:
                raise AgentError("Model response is missing or exceeds the 100 KB limit.")
            try:
                action = _parse_action(reply.content)
            except (TypeError, json.JSONDecodeError) as exc:
                raise AgentError("Model response was not valid JSON; refusing to guess or execute.") from exc
            if not isinstance(action, dict):
                raise AgentError("Model response must be a JSON object.")
            if "final" in action:
                if set(action) != {"final"} or not isinstance(action["final"], str):
                    raise AgentError("Final response must contain only a string 'final' field.")
                return action["final"]
            if set(action) != {"tool", "arguments"}:
                raise AgentError("Tool response must contain only 'tool' and 'arguments'.")
            tool = action["tool"]
            args = action["arguments"]
            if not isinstance(args, dict):
                raise AgentError("Tool arguments must be a JSON object.")
            try:
                if tool == "read_file":
                    result = self.tools.read_file(args.get("path"))
                elif tool == "write_file":
                    result = self.tools.write_file(args.get("path"), args.get("content"))
                elif tool == "replace_text":
                    result = self.tools.replace_text(args.get("path"), args.get("old_text"), args.get("new_text"))
                elif tool == "run_tests":
                    result = self.tools.run_tests(args.get("command"))
                else:
                    raise ToolError("Unknown tool.")
            except (ToolError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
                result = f"TOOL_ERROR: {type(exc).__name__}: {exc}"
            messages.extend([{"role": "assistant", "content": reply.content}, {"role": "user", "content": result}])
        raise AgentError(f"Agent reached the {self.max_steps}-step limit without a final response.")
