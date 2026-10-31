const MODEL_ID = "@cf/zai-org/glm-4.7-flash";
const MAX_BODY_BYTES = 64 * 1024;
const MAX_MESSAGES = 24;
const MAX_MESSAGE_CHARS = 12_000;
const MAX_TOTAL_CHARS = 48_000;
const MAX_OUTPUT_TOKENS = 4096;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}

function constantTimeEqual(left, right) {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  let difference = a.length ^ b.length;
  const length = Math.max(a.length, b.length);
  for (let i = 0; i < length; i += 1) {
    difference |= (a[i] || 0) ^ (b[i] || 0);
  }
  return difference === 0;
}

function authorized(request, env) {
  const expected = env.STREAMIOV_AI_WORKER_TOKEN;
  if (typeof expected !== "string" || expected.length < 32) return "not-configured";
  const header = request.headers.get("authorization") || "";
  if (!header.startsWith("Bearer ")) return false;
  return constantTimeEqual(header.slice(7), expected);
}

async function readJsonLimited(request) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_BODY_BYTES) throw new Error("body-too-large");
  if (!request.body) throw new Error("missing-body");

  const reader = request.body.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_BODY_BYTES) {
      await reader.cancel();
      throw new Error("body-too-large");
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new Error("invalid-json");
  }
}

function validatePayload(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "invalid-json-object";
  if (payload.model && payload.model !== MODEL_ID) return "unsupported-model";
  if (payload.stream === true) return "streaming-not-supported";
  if (!Array.isArray(payload.messages) || payload.messages.length < 1 || payload.messages.length > MAX_MESSAGES) {
    return "invalid-messages";
  }

  let totalChars = 0;
  for (const message of payload.messages) {
    if (!message || typeof message !== "object" || Array.isArray(message)) return "invalid-message";
    if (!["system", "user", "assistant"].includes(message.role)) return "invalid-message-role";
    if (typeof message.content !== "string" || message.content.length > MAX_MESSAGE_CHARS) return "invalid-message-content";
    totalChars += message.content.length;
    if (totalChars > MAX_TOTAL_CHARS) return "prompt-too-large";
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/health" && url.pathname !== "/v1/chat/completions") {
      return json({ error: { code: "not_found", message: "Not found." } }, 404);
    }

    const auth = authorized(request, env);
    if (auth === "not-configured") {
      return json({ error: { code: "service_not_configured", message: "AI worker authentication is not configured." } }, 503);
    }
    if (!auth) {
      return json({ error: { code: "unauthorized", message: "Valid bearer authentication is required." } }, 401);
    }

    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true, service: "streamiov-ai-worker", model: MODEL_ID, authentication: "verified" });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") {
      return json({ error: { code: "method_not_allowed", message: "Method not allowed." } }, 405);
    }
    if (!env.AI || typeof env.AI.run !== "function") {
      return json({ error: { code: "inference_not_configured", message: "Workers AI binding is unavailable." } }, 503);
    }

    let payload;
    try {
      payload = await readJsonLimited(request);
    } catch (error) {
      const code = error.message === "body-too-large" ? "request_too_large" : "invalid_request";
      const status = error.message === "body-too-large" ? 413 : 400;
      return json({ error: { code, message: "Request body is invalid or too large." } }, status);
    }

    const invalid = validatePayload(payload);
    if (invalid) {
      return json({ error: { code: invalid, message: "Chat request failed validation." } }, 400);
    }

    try {
      const result = await env.AI.run(MODEL_ID, {
        messages: payload.messages,
        temperature: 0.1,
        max_tokens: MAX_OUTPUT_TOKENS
      });
      const content = result && typeof result.response === "string" ? result.response : "";
      if (!content.trim()) {
        return json({ error: { code: "empty_model_response", message: "The model returned no text." } }, 502);
      }
      return json({
        id: crypto.randomUUID(),
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model: MODEL_ID,
        choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }]
      });
    } catch (error) {
      const message = String(error && error.message || "");
      const limited = /quota|limit|neuron|rate/i.test(message);
      return json({
        error: {
          code: limited ? "daily_ai_limit_reached" : "inference_unavailable",
          message: limited
            ? "The free daily AI allocation is exhausted. Requests are paused until it resets."
            : "Cloudflare Workers AI is temporarily unavailable. No paid fallback is configured."
        }
      }, limited ? 429 : 503);
    }
  }
};
