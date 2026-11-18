#!/usr/bin/env python3
"""Run one explicitly agent-ready GitHub issue locally with live terminal progress."""
from __future__ import annotations
import argparse, base64, json, os, shutil, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('issue', type=int, help='GitHub issue number (must be labeled agent-ready)')
    parser.add_argument('--database', default=str(ROOT / '.streamiov' / 'ai-missions.sqlite3'))
    args = parser.parse_args()
    if args.issue < 1: parser.error('issue must be a positive GitHub issue number')
    gh = shutil.which('gh')
    if not gh:
        print("ERROR: GitHub CLI 'gh' is required. Install it and run 'gh auth login'.", file=sys.stderr)
        return 2
    try:
        completed = subprocess.run([gh, 'issue', 'view', str(args.issue), '--json', 'number,title,body,labels'], cwd=ROOT, check=True, capture_output=True, text=True, timeout=30)
        issue = json.loads(completed.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, 'stderr', '') or str(exc)
        print(f'ERROR: Could not read GitHub issue: {detail.strip()}', file=sys.stderr)
        return 2
    labels = {item.get('name', '') for item in issue.get('labels', []) if isinstance(item, dict)}
    if 'agent-blocked' in labels or 'agent-in-progress' in labels or 'agent-ready' not in labels:
        print('REFUSED: Issue must have agent-ready and must not have agent-blocked/agent-in-progress. Current labels: ' + (', '.join(sorted(labels)) or '(none)'), file=sys.stderr)
        return 2
    if not isinstance(issue.get('body'), str) or not issue['body'].strip():
        print('ERROR: Issue has no task body.', file=sys.stderr)
        return 2
    payload = {'number': issue['number'], 'title': issue['title'], 'body': issue['body']}
    os.environ['STREAMIOV_AGENT_ISSUE_B64'] = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode('utf-8')).decode('ascii')
    os.environ['STREAMIOV_MISSION_ID'] = f"streamiov-issue-{issue['number']}"
    os.environ['STREAMIOV_MISSION_DB'] = str(Path(args.database).expanduser().resolve())
    os.environ.setdefault('GITHUB_RUN_ID', 'local-terminal')
    os.environ.setdefault('GITHUB_RUN_ATTEMPT', '1')
    print(f"Starting local AI Chief mission for issue #{issue['number']}: {issue['title']}", flush=True)
    print(f"Mission database: {os.environ['STREAMIOV_MISSION_DB']}", flush=True)
    print('Live progress is shown below. Press Ctrl+C to stop safely; restart with the same issue to resume.', flush=True)
    from scripts.autonomous.run_issue import main as run_mission
    return run_mission()

if __name__ == '__main__': raise SystemExit(main())