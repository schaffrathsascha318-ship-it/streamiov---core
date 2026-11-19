# STREAMIOV local terminal executor (Chromebook)

## Status

This is the first local execution client, not a working remote-control connection yet. The Cloudflare control-plane routes it expects must be implemented and deployed before it can claim jobs. No command is run merely by installing this package.

The executor is intentionally outbound-only. It does not expose an SSH server, web terminal, inbound port, arbitrary shell, or arbitrary command arguments.

## Fixed command profiles

- `diagnostics`: Python version, Git version, and Git working-tree status.
- `git-status`: Git working-tree status only.
- `python-tests`: `python -m unittest discover -s tests -v`.

The server can choose only one of these names. The executor maps each name to fixed argv arrays and always uses `shell=False`. No command, path, environment variable, or argument is accepted from a remote job.

## Job authentication and replay protection

A claimed job must be an HMAC-SHA256 signed envelope with exactly these fields: `id`, `device_id`, `profile`, `issued_at`, `expires_at`, `nonce`, and empty `args`. Jobs are limited to a five-minute validity window, bound to one device, and verified with constant-time signature comparison. The local SQLite audit ledger rejects a job ID already seen, including a job left in an uncertain running state after a crash. This intentionally prefers a manual recovery over accidental duplicate execution.

The device bearer token authenticates HTTPS requests. The separate signing key verifies jobs. Neither credential is passed to child commands. The executor accepts only an HTTPS `workers.dev` origin and uses fixed API paths.

## Resource and filesystem boundaries

- Workspace must resolve exactly to `~/streamiov`; workspace symlinks are rejected.
- Audit database must stay under `data/ai-development/`.
- A minimum of 250 MiB free disk space is required before execution.
- Child process working directory is always the workspace.
- Child environment is reduced to PATH and HOME.
- Stdout/stderr are capped and common credential patterns redacted.
- Execution timeout is bounded (default 180 seconds; hard range 10–900).
- No deletion, file editing, package installation, arbitrary build, deployment, OAuth, payments, or production operation is exposed.

## Expected control-plane API contract (not yet deployed)

The client expects:
- `POST /v1/devices/{device_id}/jobs/claim` with `{"device_id":"..."}`.
- Idle response: `{"status":"idle"}`.
- Job response: `{"job":{...},"signature":"<hex HMAC-SHA256>"}`.
- `POST /v1/devices/{device_id}/jobs/{job_id}/complete` with job ID, profile, status, exit code, timestamps, duration, SHA-256 digest and bounded output.

The server must authenticate device identity, enforce device registration/revocation, issue a job at most once, persist claims and completion records, verify idempotency, and never accept commands from the client. Signing keys must be generated and provisioned securely per environment; do not reuse the model gateway token as the job-signing key.

## Local setup (only after the control-plane API is deployed)

1. Verify the repository and Python environment exist:
   `cd ~/streamiov && .venv/bin/python --version`
2. Create `~/.config/streamiov/device.env` with mode 0600. It must contain only:
   - `STREAMIOV_DEVICE_ID`
   - `STREAMIOV_CONTROL_URL`
   - `STREAMIOV_DEVICE_TOKEN`
   - `STREAMIOV_JOB_SIGNING_KEY`
3. Run the non-executing configuration check:
   `cd ~/streamiov && .venv/bin/python -m ai.runtime.local_terminal_executor --doctor`
4. Test one harmless job only after a device is registered and the API is verified:
   `cd ~/streamiov && .venv/bin/python -m ai.runtime.local_terminal_executor --once`

Never paste device credentials into chat, GitHub issues, commits, or logs.

## Optional systemd user service

First check whether Crostini provides a working user systemd manager:

```bash
systemctl --user is-system-running
```

Only if that succeeds, install the service template:

```bash
mkdir -p ~/.config/systemd/user ~/.config/streamiov
cp ~/streamiov/infrastructure/systemd/streamiov-local-executor.service ~/.config/systemd/user/
chmod 600 ~/.config/streamiov/device.env
systemctl --user daemon-reload
systemctl --user enable --now streamiov-local-executor.service
systemctl --user status streamiov-local-executor.service
journalctl --user -u streamiov-local-executor.service -n 100 --no-pager
```

Stop/pause:
```bash
systemctl --user stop streamiov-local-executor.service
systemctl --user disable streamiov-local-executor.service
```

Do not enable lingering automatically. Device revocation must also happen in the cloud control plane; stopping the local service alone does not revoke a leaked device credential.

## Remaining acceptance work

- Implement and deploy the authenticated Cloudflare device/job API, durable queue and audit records.
- Add secure device enrollment and revocation.
- Add signed job issuance, server-side idempotency, claim leases and completion persistence.
- Test this client against a local mock server and then the real Cloudflare API.
- Run a harmless diagnostic on the actual Chromebook and capture stdout, stderr, exit code and audit digest.
- Add build/package profiles only after each exact command is reviewed and tested.
- Add monitoring and recovery for jobs interrupted by power loss or network outage.
