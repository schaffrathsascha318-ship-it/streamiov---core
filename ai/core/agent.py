"""Small tool-using development agent backed by a real local model endpoint."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from ai.runtime.project_tools import ProjectTools, ToolError
from ai.providers.base import ModelProvider
from ai.core.specialists import get_specialist, system_prompt

SYSTEM = """You are Streamiov's coding agent. Work only on the supplied project task.
You may request exactly one JSON object per response:
{"tool":"read_file","arguments":{"path":"relative/path"}}
{"tool":"write_file","arguments":{"path":"new/relative/path","content":"complete file text"}}
{"tool":"replace_text","arguments":{"path":"ai/file.py","old_text":"one exact existing section","new_text":"its replacement"}}
{"tool":"run_tests","arguments":{"command":"python -m unittest discover -s tests"}}
{"tool":"run_game_checks","arguments":{}}
{"final":"concise result"}
Never request secrets, environment files, credentials, OAuth data, production actions, arbitrary shell commands, network access, or overwriting files wholesale. Exact-match edits must target one unique section. Paths and tools are enforced independently. Do not claim a test passed unless its output proves it. Return JSON only."""

MAX_MODEL_REPLY_CHARS = 100_000
MAX_ACTIONS_PER_REPLY = 6


# Cloudflare Worker request limits, including the separately sent system prompt.
MAX_PROVIDER_MESSAGES = 24
MAX_PROVIDER_MESSAGE_CHARS = 12_000
MAX_PROVIDER_TOTAL_CHARS = 48_000


def _fit_provider_messages(system: str, messages: list[dict]) -> list[dict]:
    """Keep the original task and newest context within Worker limits."""
    if len(system) > MAX_PROVIDER_MESSAGE_CHARS:
        raise AgentError("System prompt exceeds the Cloudflare message limit.")

    budget = MAX_PROVIDER_TOTAL_CHARS - len(system)
    cleaned = []

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        if len(content) > MAX_PROVIDER_MESSAGE_CHARS:
            marker = "\\n[... content shortened to fit Worker limits ...]"
            content = content[:MAX_PROVIDER_MESSAGE_CHARS - len(marker)] + marker
        cleaned.append({"role": role, "content": content})

    if not cleaned or cleaned[0]["role"] != "user":
        raise AgentError("Conversation history lost its original user task.")

    selected = [cleaned[0]]
    used = len(cleaned[0]["content"])
    if used > budget:
        raise AgentError("Original task does not fit the Worker request limit.")

    recent = []
    for message in reversed(cleaned[1:]):
        if len(selected) + len(recent) >= MAX_PROVIDER_MESSAGES - 1:
            break
        size = len(message["content"])
        if used + size <= budget:
            recent.append(message)
            used += size

    selected.extend(reversed(recent))
    return selected


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    return text


def _parse_actions(content: str) -> list:
    """Parse one or more adjacent JSON objects, optionally inside one Markdown fence."""
    text = _strip_json_fence(content)
    decoder = json.JSONDecoder()
    actions = []
    while text.strip():
        text = text.lstrip()
        action, end = decoder.raw_decode(text)
        actions.append(action)
        text = text[end:]
        if len(actions) > MAX_ACTIONS_PER_REPLY:
            raise ValueError(f"Model returned more than {MAX_ACTIONS_PER_REPLY} actions in one response.")
    if not actions:
        raise json.JSONDecodeError("Empty model response", text, 0)
    return actions


def _parse_action(content: str):
    """Compatibility helper for callers that require exactly one JSON object."""
    actions = _parse_actions(content)
    if len(actions) != 1:
        raise ValueError("Expected exactly one JSON object.")
    return actions[0]


class AgentError(RuntimeError):
    pass


class DevelopmentAgent:
    def __init__(
        self,
        provider: ModelProvider,
        project_root: str | Path,
        max_steps: int = 12,
        specialist: str = "software",
    ) -> None:
        if not 1 <= max_steps <= 30:
            raise ValueError("max_steps must be between 1 and 30")
        self.provider = provider
        role = get_specialist(specialist)
        self.specialist = role
        self.tools = ProjectTools(
            project_root,
            writable_prefixes=role.writable_prefixes,
            allow_game_checks=role.name == "games",
        )
        self.system = system_prompt(specialist, SYSTEM)
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        if not isinstance(task, str) or not task.strip() or len(task) > 8000:
            raise ValueError("Task must contain 1–8000 characters.")
        messages = [{"role": "user", "content": task.strip()}]
        format_retries = 0
        for _ in range(self.max_steps):
            messages = _fit_provider_messages(self.system, messages)
            reply = self.provider.generate(system=self.system, messages=messages)
            if not isinstance(reply.content, str) or len(reply.content) > MAX_MODEL_REPLY_CHARS:
                raise AgentError("Model response is missing or exceeds the 100 KB limit.")
            try:
                actions = _parse_actions(reply.content)
            except (TypeError, json.JSONDecodeError, ValueError) as exc:
                if format_retries >= 1:
                    raise AgentError("Model response was not a valid sequence of JSON actions after one format retry; refusing to guess or execute.") from exc
                format_retries += 1
                messages.extend([
                    {
                        "role": "assistant",
                        "content": "My previous response did not follow the required action protocol.",
                    },
                    {
                        "role": "user",
                        "content": (
                            "FORMAT CORRECTION: Return only valid JSON action objects in the "
                            "required protocol. No explanations, prose, headings, or text outside "
                            "JSON. Do not claim that an action was executed. If finished, return "
                            'exactly {"final":"your concise result"}.'
                        ),
                    },
                ])
                continue
            if any(not isinstance(action, dict) for action in actions):
                raise AgentError("Every model action must be a JSON object.")
            if any("final" in action for action in actions):
                if len(actions) != 1 or set(actions[0]) != {"final"} or not isinstance(actions[0]["final"], str):
                    raise AgentError("A final response must be the only object and contain only a string 'final' field.")
                return actions[0]["final"]

            # Validate the entire batch before executing any action.
            for action in actions:
                if set(action) != {"tool", "arguments"}:
                    raise AgentError("Tool response must contain only 'tool' and 'arguments'.")
                allowed_tools = {"read_file", "write_file", "replace_text", "run_tests"}
                if self.specialist.name == "games":
                    allowed_tools.add("run_game_checks")
                if action["tool"] not in allowed_tools:
                    raise AgentError("Unknown tool.")
                if not isinstance(action["arguments"], dict):
                    raise AgentError("Tool arguments must be a JSON object.")

            results = []
            for index, action in enumerate(actions, start=1):
                tool = action["tool"]
                args = action["arguments"]
                try:
                    if tool == "read_file":
                        result = self.tools.read_file(args.get("path"))
                    elif tool == "write_file":
                        result = self.tools.write_file(args.get("path"), args.get("content"))
                    elif tool == "replace_text":
                        result = self.tools.replace_text(args.get("path"), args.get("old_text"), args.get("new_text"))
                    elif tool == "run_game_checks":
                        if args:
                            raise ToolError("run_game_checks takes no arguments.")
                        result = self.tools.run_game_checks()
                    else:
                        result = self.tools.run_tests(args.get("command"))
                except (ToolError, OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
                    result = f"TOOL_ERROR: {type(exc).__name__}: {exc}"
                results.append(f"ACTION {index} ({tool}):\n{result}")

            # Retain concise tool context, not the full JSON action payload.
            action_context = ", ".join(str(action["tool"]) for action in actions)
            result_context = "\\n\\n".join(results)
            messages.extend([
                {
                    "role": "assistant",
                    "content": f"Previously requested tools: {action_context}",
                },
                {
                    "role": "user",
                    "content": result_context[:10_000],
                },
            ])
        raise AgentError(f"Agent reached the {self.max_steps}-step limit without a final response.")
