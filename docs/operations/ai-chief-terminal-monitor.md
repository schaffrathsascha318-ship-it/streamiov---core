# AI Chief: live terminal monitoring

The autonomous specialist runner emits timestamped, human-readable events while it works. Output reports the current specialist, model request, planned actions, tool starts/completions, bounded format corrections, task results, and mission checkpoints. Prompts, model responses, file contents, and credentials are deliberately not printed.

## Run a ready mission locally

Requirements: Python 3.10+, GitHub CLI (`gh`) authenticated for this repository, and a local Ollama server or another supported local OpenAI-compatible endpoint with the configured model available.

From the repository root:

```bash
gh auth status
export STREAMIOV_MODEL_PROVIDER=ollama
export STREAMIOV_MODEL=qwen2.5-coder:7b
export STREAMIOV_MODEL_URL=http://127.0.0.1:11434
python3 scripts/autonomous/run_local.py 145
```

The launcher reads the issue through `gh` and refuses to run unless it has `agent-ready` and does not have `agent-blocked` or `agent-in-progress`. It uses `.streamiov/ai-missions.sqlite3`; rerunning the same issue resumes the same mission. `Ctrl+C` requests a safe stop and checkpoints the mission.

Do not remove a blocker label just to start execution. Issue #145 must remain blocked until the specialist protocol repair has passed CI and independent review. Once explicitly made `agent-ready`, run the command above.

## Example output

```text
[21:04:11] [code] agent_started
[21:04:12] [code] model_request message_count=1
[21:04:18] [code] actions_received action_count=2 tools=['list_files', 'read_file']
[21:04:18] [code] tool_started tool=list_files action_index=1 action_count=2
[21:04:18] [code] tool_completed tool=list_files action_index=1 success=True result_chars=842
[21:04:19] [code] tool_started tool=read_file action_index=2 action_count=2 path=src/example.py
[21:04:19] [code] tool_completed tool=read_file action_index=2 success=True result_chars=2140
```

This is live execution output, not a simulated animation. A completed tool event means the local tool returned; it does not by itself mean the overall mission or release is complete.