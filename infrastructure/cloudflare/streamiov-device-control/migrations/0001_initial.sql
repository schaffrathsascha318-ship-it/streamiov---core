PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
  status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'revoked')),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  encrypted_signing_key TEXT NOT NULL,
  key_iv TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER,
  revoked_at INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  device_id TEXT NOT NULL REFERENCES devices(id),
  profile TEXT NOT NULL CHECK (profile IN ('diagnostics', 'git-status', 'python-tests')),
  status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'succeeded', 'failed', 'uncertain', 'expired')),
  idempotency_key TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (length(reason) BETWEEN 1 AND 240),
  issued_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  nonce TEXT NOT NULL,
  claimed_at INTEGER,
  lease_expires_at INTEGER,
  completed_at INTEGER,
  exit_code INTEGER,
  duration_seconds INTEGER,
  result_sha256 TEXT,
  output TEXT,
  completion_digest TEXT,
  UNIQUE (device_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_device_status_issued
  ON jobs (device_id, status, issued_at);

CREATE INDEX IF NOT EXISTS idx_jobs_status_lease
  ON jobs (status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_devices_status_created
  ON devices (status, created_at);
