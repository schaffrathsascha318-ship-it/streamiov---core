# Persistent AI Chief supervisor service

The repository already contains a durable project supervisor (`python -m ai --project-supervisor-run`) and a separate specialist queue worker. The specialist worker service does not start the project supervisor. This systemd unit runs the persistent AI Chief process itself, so a completed mission can be followed by the next mission without an interactive terminal.

## Configure on the private Linux development host

1. Ensure the repository is at `/opt/streamiov`, the virtual environment exists at `/opt/streamiov/.venv`, and the `streamiov` service user owns the working tree.
2. Copy `infrastructure/systemd/streamiov-ai-chief.env.example` to `/etc/streamiov/ai-chief.env`.
3. Set the real AI Worker URL and private `STREAMIOV_AI_WORKER_TOKEN` (or configure the local Ollama alternative). The AI Worker token is not the Core API token. Set a single persistent project goal; the supervisor initializes it once and will not overwrite an existing stored goal on restart.
4. Protect the environment file: `sudo chown root:streamiov /etc/streamiov/ai-chief.env && sudo chmod 0640 /etc/streamiov/ai-chief.env`.
5. The unit runs a local preflight before starting: it rejects an empty/oversized project goal, unsupported provider, unpinned Cloudflare model, placeholder/short Worker token, and malformed or non-HTTPS workers.dev origin. It never prints the token.
6. Install and enable the unit:

   ```sh
   sudo install -m 0644 infrastructure/systemd/streamiov-ai-chief-supervisor.service.example /etc/systemd/system/streamiov-ai-chief-supervisor.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now streamiov-ai-chief-supervisor.service
   ```

7. Inspect operation with `systemctl status streamiov-ai-chief-supervisor.service` and `journalctl -u streamiov-ai-chief-supervisor.service -f`.

## Safety and behavior

- Runs as the unprivileged `streamiov` user; no root process, shell login or Chromebook hosting requirement.
- Uses a persistent SQLite mission database and supervisor lease under `/var/lib/streamiov`. A second supervisor instance cannot acquire the active lease.
- `--full-project-development` and `--allow-self-modification` permit project source development, while the existing ProjectTools protected-path policy continues to block secrets, GitHub workflows, autonomous runner controls and deployment configuration.
- The service does not install or enable itself, create credentials, change Cloudflare resources, deploy Workers, rotate OAuth, publish releases, or bypass existing review/rollback controls.
- The configured model provider must be reachable. The Cloudflare provider is pinned to the existing Streamiov AI Worker model; local Ollama remains an alternative. No paid model fallback is configured.
- Restarting the service resumes the same persisted project goal and mission checkpoints; it does not create a new goal on every restart.
- This service is a persistent supervisor, not a substitute for specialist queue workers where the queue architecture is used. Do not run duplicate supervisors against the same mission database.

## Deployment boundary

The unit and environment template are source-only until installed on the actual private Linux host. No service was started or enabled by this PR. A real model URL/token, service user, working tree and provider readiness are required.
