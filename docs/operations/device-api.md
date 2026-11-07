# OpenCode Core device enrollment API

## Purpose and security boundary

This API lets a user pair a control device with an existing trusted Core host. The host remains the only place that owns the workspace, worker queue, provider credentials, and persistent execution state. Pairing does not grant a remote device filesystem access or task execution rights.

## Endpoints

| Method | Path | Authentication | Purpose |
|---|---|---|---|
| POST | `/api/v1/devices/pairing-code` | Account session + same-origin or local Studio client | Create one active, single-use pairing code for the signed-in account |
| POST | `/api/v1/devices/enroll` | Pairing code | Enroll a device and return its bearer token once |
| GET | `/api/v1/devices` | Account session | List the account's devices and status metadata |
| POST | `/api/v1/devices/{device_id}/revoke` | Account session + same-origin or local Studio client | Revoke one device |
| GET | `/api/v1/device/status` | Device bearer token with `status:read` | Return non-sensitive host and enrolled-device status |

## Credential lifecycle

- Pairing codes are generated from cryptographically secure random bytes, stored only as SHA-256 hashes, expire after five minutes, and can be used once.
- Only one pending pairing code per account is active; issuing a new code invalidates the previous one.
- Device tokens are generated from 256 bits of randomness, stored only as SHA-256 hashes, shown only in the enrollment response, and expire after 90 days.
- Devices receive only the `status:read` scope. No task-control or workspace scope is issued.
- The account owner can list and revoke devices. Password reset revokes all active device tokens and pending pairing codes.
- Pairing and enrollment endpoints are rate-limited. Remote enrollment requires HTTPS/TLS; loopback enrollment is permitted for local development.
- Clients must store the device token in the operating system's secure credential store and must never put it in URLs, logs, crash reports, or source control.

## Explicitly not available yet

- Task submission, queue inspection, cancellation, or worker control.
- Workspace file browsing or editing from a remote device.
- Native OpenCode Core clients for ChromeOS, Android, or iOS.
- Device sync, offline queueing, reconnect UX, push notifications, or real-device certification.

The API is an initial authentication foundation, not a production-ready remote-control release. Keep the host on loopback until TLS, access policy, audit logging, and representative device verification are complete.
