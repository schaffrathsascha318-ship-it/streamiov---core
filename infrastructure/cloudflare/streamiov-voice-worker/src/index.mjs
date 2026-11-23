const MAX_TOKEN_TTL = 300;
const MAX_ROOM_PARTICIPANTS = 8;
const MAX_MESSAGE_BYTES = 64 * 1024;
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = 90;
const ROOM_ID = /^[a-f0-9]{32}$/;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer"
    }
  });
}

function decodeBase64Url(value) {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(normalized + "=".repeat((4 - normalized.length % 4) % 4));
  return Uint8Array.from(binary, char => char.charCodeAt(0));
}

function encodeBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256(value) {
  return encodeBase64Url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))));
}

async function verifyVoiceToken(token, env, roomId) {
  if (typeof env.STREAMIOV_VOICE_SIGNING_KEY !== "string" || env.STREAMIOV_VOICE_SIGNING_KEY.length < 32) {
    return { error: "not_configured" };
  }
  if (typeof token !== "string" || token.length > 4096) return { error: "unauthorized" };
  const parts = token.split(".");
  if (parts.length !== 3) return { error: "unauthorized" };
  let header, claims, signature;
  try {
    header = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[0])));
    claims = JSON.parse(new TextDecoder().decode(decodeBase64Url(parts[1])));
    signature = decodeBase64Url(parts[2]);
  } catch {
    return { error: "unauthorized" };
  }
  if (header?.alg !== "HS256" || header?.typ !== "JWT" ||
      claims?.iss !== "streamiov-core" || claims?.aud !== "streamiov-voice" ||
      typeof claims.sub !== "string" || !claims.sub || claims.room !== roomId ||
      !["owner", "moderator", "member", "guest"].includes(claims.role) ||
      typeof claims.jti !== "string" || claims.jti.length < 16 ||
      !Number.isInteger(claims.iat) || !Number.isInteger(claims.nbf) || !Number.isInteger(claims.exp)) {
    return { error: "unauthorized" };
  }
  const now = Math.floor(Date.now() / 1000);
  if (claims.nbf > now + 5 || claims.iat > now + 5 || claims.exp <= now ||
      claims.exp - claims.iat > MAX_TOKEN_TTL) return { error: "expired" };
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(env.STREAMIOV_VOICE_SIGNING_KEY),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const expected = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(parts[0] + "." + parts[1])));
  if (signature.length !== expected.length || !constantTimeEqual(signature, expected)) return { error: "unauthorized" };
  return { claims };
}

function constantTimeEqual(a, b) {
  let difference = a.length ^ b.length;
  const size = Math.max(a.length, b.length);
  for (let i = 0; i < size; i += 1) difference |= (a[i] || 0) ^ (b[i] || 0);
  return difference === 0;
}

function allowedOrigin(request, env) {
  const origin = request.headers.get("origin");
  if (!origin || origin === "null") return true; // desktop clients use one-time tickets, not ambient cookies
  const allowlist = String(env.STREAMIOV_VOICE_ALLOWED_ORIGINS || "")
    .split(",").map(value => value.trim()).filter(Boolean);
  return allowlist.includes(origin);
}

function roomStub(env, roomId) {
  if (!env.VOICE_ROOMS) throw new Error("voice_binding_missing");
  return env.VOICE_ROOMS.get(env.VOICE_ROOMS.idFromName(roomId));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      const configured = typeof env.STREAMIOV_VOICE_SIGNING_KEY === "string" &&
        env.STREAMIOV_VOICE_SIGNING_KEY.length >= 32 && Boolean(env.VOICE_ROOMS);
      return json({ ok: true, service: "streamiov-voice-signalling", configured, transport: "webrtc-peer-to-peer", media_recording: false });
    }
    if (url.pathname === "/v1/voice/ticket") {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      if (!allowedOrigin(request, env)) return json({ error: "origin_not_allowed" }, 403);
      const auth = request.headers.get("authorization") || "";
      if (!auth.startsWith("Bearer ")) return json({ error: "unauthorized" }, 401);
      const token = auth.slice(7);
      // The room is authenticated from the signed claim before any DO lookup.
      const segments = token.split(".");
      let roomId = "";
      try { roomId = JSON.parse(new TextDecoder().decode(decodeBase64Url(segments[1]))).room; } catch {}
      if (!ROOM_ID.test(roomId || "")) return json({ error: "unauthorized" }, 401);
      const verified = await verifyVoiceToken(token, env, roomId);
      if (verified.error) return json({ error: verified.error }, verified.error === "not_configured" ? 503 : 401);
      let stub;
      try { stub = roomStub(env, roomId); } catch { return json({ error: "service_not_configured" }, 503); }
      const ticket = encodeBase64Url(crypto.getRandomValues(new Uint8Array(32)));
      const expiresAt = Date.now() + 60_000;
      const response = await stub.fetch("https://voice-room.internal/ticket", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ hash: await sha256(ticket), expiresAt, claims: verified.claims })
      });
      if (!response.ok) return json({ error: "ticket_issue_failed" }, 503);
      return json({ ticket, expires_in: 60, websocket_url: url.origin.replace(/^http/, "ws") + "/v1/voice/rooms/" + roomId });
    }
    const closeMatch = url.pathname.match(/^\/v1\/voice\/rooms\/([a-f0-9]{32})\/close$/);
    if (closeMatch) {
      if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
      if (!allowedOrigin(request, env)) return json({ error: "origin_not_allowed" }, 403);
      const auth = request.headers.get("authorization") || "";
      if (!auth.startsWith("Bearer ")) return json({ error: "unauthorized" }, 401);
      const verified = await verifyVoiceToken(auth.slice(7), env, closeMatch[1]);
      if (verified.error) return json({ error: verified.error }, verified.error === "not_configured" ? 503 : 401);
      if (verified.claims.role !== "owner") return json({ error: "owner_required" }, 403);
      let stub;
      try { stub = roomStub(env, closeMatch[1]); } catch { return json({ error: "service_not_configured" }, 503); }
      return stub.fetch("https://voice-room.internal/close", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ claims: verified.claims })
      });
    }
    const match = url.pathname.match(/^\/v1\/voice\/rooms\/([a-f0-9]{32})$/);
    if (match) {
      if (request.method !== "GET" || request.headers.get("upgrade")?.toLowerCase() !== "websocket") {
        return json({ error: "websocket_upgrade_required" }, 426);
      }
      if (!allowedOrigin(request, env)) return json({ error: "origin_not_allowed" }, 403);
      const ticket = url.searchParams.get("ticket") || "";
      if (!/^[A-Za-z0-9_-]{40,64}$/.test(ticket)) return json({ error: "ticket_required" }, 401);
      let stub;
      try { stub = roomStub(env, match[1]); } catch { return json({ error: "service_not_configured" }, 503); }
      return stub.fetch(request);
    }
    return json({ error: "not_found" }, 404);
  }
};

export class VoiceRoom {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/ticket") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
      if (!body || typeof body.hash !== "string" || !Number.isFinite(body.expiresAt) ||
          !body.claims || typeof body.claims.sub !== "string" || body.expiresAt <= Date.now() ||
          body.expiresAt > Date.now() + 60_000) return json({ error: "invalid_ticket" }, 400);
      if (await this.state.storage.get("closed")) return json({ error: "room_closed" }, 410);
      await this.state.storage.put("ticket:" + body.hash, { expiresAt: body.expiresAt, claims: body.claims });
      return json({ ok: true }, 201);
    }
    if (request.method === "POST" && url.pathname === "/close") {
      let body;
      try { body = await request.json(); } catch { return json({ error: "invalid_json" }, 400); }
      if (body?.claims?.role !== "owner" || typeof body.claims.sub !== "string") return json({ error: "owner_required" }, 403);
      await this.state.storage.put("closed", true);
      const pending = await this.state.storage.list({ prefix: "ticket:" });
      if (pending.size) await this.state.storage.delete([...pending.keys()]);
      for (const socket of this.state.getWebSockets()) {
        try { socket.close(4001, "room_closed"); } catch {}
      }
      return json({ ok: true, closed: true });
    }
    if (request.method === "GET" && request.headers.get("upgrade")?.toLowerCase() === "websocket") {
      if (await this.state.storage.get("closed")) return json({ error: "room_closed" }, 410);
      const ticket = url.searchParams.get("ticket") || "";
      const hash = await sha256(ticket);
      let record;
      try {
        record = await this.state.storage.transaction(async txn => {
          const key = "ticket:" + hash;
          const found = await txn.get(key);
          if (!found || found.expiresAt <= Date.now()) {
            if (found) await txn.delete(key);
            return null;
          }
          await txn.delete(key);
          return found;
        });
      } catch {
        return json({ error: "ticket_storage_unavailable" }, 503);
      }
      if (!record) return json({ error: "ticket_invalid_or_used" }, 401);
      const sockets = this.state.getWebSockets();
      if (sockets.length >= MAX_ROOM_PARTICIPANTS) return json({ error: "room_full" }, 409);
      const pair = new WebSocketPair();
      const client = pair[0];
      const server = pair[1];
      const participantId = crypto.randomUUID();
      const attachment = {
        participantId,
        userId: record.claims.sub,
        role: record.claims.role,
        joinedAt: Date.now(),
        windowStartedAt: Date.now(),
        messageCount: 0
      };
      server.serializeAttachment(attachment);
      this.state.acceptWebSocket(server);
      const participants = this.state.getWebSockets().map(socket => socket.deserializeAttachment()).filter(Boolean);
      server.send(JSON.stringify({ type: "ready", participantId, participants }));
      this.#broadcast({ type: "participant-joined", participant: { participantId, userId: attachment.userId, role: attachment.role } }, server);
      return new Response(null, { status: 101, webSocket: client });
    }
    return json({ error: "not_found" }, 404);
  }

  async webSocketMessage(socket, raw) {
    const size = typeof raw === "string" ? new TextEncoder().encode(raw).byteLength : raw?.byteLength || 0;
    if (size < 2 || size > MAX_MESSAGE_BYTES) {
      try { socket.close(1009, "message_too_large"); } catch {}
      return;
    }
    let message;
    try { message = JSON.parse(typeof raw === "string" ? raw : new TextDecoder().decode(raw)); } catch {
      socket.send(JSON.stringify({ type: "error", code: "invalid_json" }));
      return;
    }
    const allowed = new Set(["offer", "answer", "ice", "mute", "deafen", "speaking", "leave", "ping"]);
    if (!message || typeof message !== "object" || Array.isArray(message) || !allowed.has(message.type)) {
      socket.send(JSON.stringify({ type: "error", code: "invalid_message" }));
      return;
    }
    const attachment = socket.deserializeAttachment();
    if (!attachment) { try { socket.close(1008, "session_missing"); } catch {} return; }
    const now = Date.now();
    if (now - attachment.windowStartedAt >= RATE_WINDOW_MS) {
      attachment.windowStartedAt = now;
      attachment.messageCount = 0;
    }
    attachment.messageCount += 1;
    if (attachment.messageCount > RATE_LIMIT) {
      socket.serializeAttachment(attachment);
      socket.send(JSON.stringify({ type: "error", code: "rate_limited" }));
      return;
    }
    socket.serializeAttachment(attachment);
    if (message.type === "ping") {
      socket.send(JSON.stringify({ type: "pong", at: now }));
      return;
    }
    if (message.type === "leave") {
      try { socket.close(1000, "left_room"); } catch {}
      return;
    }
    if (["mute", "deafen", "speaking"].includes(message.type)) {
      if (typeof message.value !== "boolean") {
        socket.send(JSON.stringify({ type: "error", code: "invalid_state" }));
        return;
      }
      this.#broadcast({ type: message.type, participantId: attachment.participantId, value: message.value }, socket);
      return;
    }
    const target = typeof message.target === "string" ? message.target : "";
    if (!target || target === attachment.participantId) {
      socket.send(JSON.stringify({ type: "error", code: "target_required" }));
      return;
    }
    let payload = message.payload;
    if (message.type === "ice") {
      if (!payload || typeof payload !== "object" || typeof payload.candidate !== "string" || payload.candidate.length > 4096) {
        socket.send(JSON.stringify({ type: "error", code: "invalid_ice_candidate" }));
        return;
      }
    } else if (!payload || typeof payload !== "object" || typeof payload.sdp !== "string" || payload.sdp.length > 48_000) {
      socket.send(JSON.stringify({ type: "error", code: "invalid_session_description" }));
      return;
    }
    const recipient = this.state.getWebSockets().find(peer => peer.deserializeAttachment()?.participantId === target);
    if (!recipient) {
      socket.send(JSON.stringify({ type: "error", code: "participant_unavailable", target }));
      return;
    }
    recipient.send(JSON.stringify({
      type: message.type,
      from: attachment.participantId,
      payload
    }));
  }

  async webSocketClose(socket, code, reason) {
    const attachment = socket.deserializeAttachment();
    this.#broadcast({ type: "participant-left", participantId: attachment?.participantId || null }, socket);
  }

  async webSocketError(socket) {
    const attachment = socket.deserializeAttachment();
    this.#broadcast({ type: "participant-left", participantId: attachment?.participantId || null }, socket);
  }

  #broadcast(message, except = null) {
    const encoded = JSON.stringify(message);
    for (const socket of this.state.getWebSockets()) {
      if (socket === except) continue;
      try { socket.send(encoded); } catch {}
    }
  }
}
