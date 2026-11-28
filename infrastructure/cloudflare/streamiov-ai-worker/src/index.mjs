const MODEL_ID = "@cf/zai-org/glm-4.7-flash";
const MAX_BODY_BYTES = 64 * 1024;
const MAX_MESSAGES = 24;
// Allow the agent to return several bounded file-read results in one tool reply.
// The total prompt and request-body limits below remain the outer safeguards.
const MAX_MESSAGE_CHARS = 32_000;
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
  if (
    payload.response_format !== undefined &&
    (!payload.response_format || typeof payload.response_format !== "object" ||
      Array.isArray(payload.response_format) || payload.response_format.type !== "json_object")
  ) return "unsupported-response-format";
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

// Workers AI model bindings may return either the legacy { response } shape
// or an OpenAI-style { choices: [{ message: { content } }] } result.
function extractModelText(result) {
  if (typeof result?.response === "string") return result.response;
  const content = result?.choices?.[0]?.message?.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((part) => part && part.type === "text" && typeof part.text === "string")
      .map((part) => part.text)
      .join("");
  }
  return "";
}


function selfHostedConfig(env) {
  const base = env.STREAMIOV_SELF_HOSTED_MODEL_URL;
  const token = env.STREAMIOV_SELF_HOSTED_MODEL_TOKEN;
  const model = env.STREAMIOV_SELF_HOSTED_MODEL || "qwen2.5-coder:7b";
  if (!base && !token) return null;
  if (typeof base !== "string" || typeof token !== "string" || token.length < 32) return null;
  try {
    const parsed = new URL(base);
    if (
      parsed.protocol !== "https:" ||
      !parsed.hostname ||
      !parsed.hostname.includes(".") ||
      !/[a-z]/i.test(parsed.hostname) ||
      parsed.hostname.toLowerCase() === "localhost" ||
      parsed.hostname.toLowerCase().endsWith(".localhost") ||
      parsed.username ||
      parsed.password ||
      parsed.search ||
      parsed.hash ||
      (parsed.port && parsed.port !== "443") ||
      !["", "/"].includes(parsed.pathname)
    ) return null;
    return { base: parsed.origin, token, model };
  } catch {
    return null;
  }
}

async function selfHostedHealth(env) {
  const config = selfHostedConfig(env);
  if (!config) return { ready: false, model: null };
  try {
    const response = await fetch(config.base + "/health", {
      method: "GET",
      headers: { authorization: `Bearer ${config.token}`, accept: "application/json" },
      redirect: "error",
      cache: "no-store"
    });
    if (!response.ok) return { ready: false, model: config.model };
    const result = await response.json();
    return {
      ready: result?.ok === true && (result?.model === config.model || result?.model_available === true),
      model: config.model
    };
  } catch {
    return { ready: false, model: config.model };
  }
}

async function selfHostedGenerate(env, payload) {
  const config = selfHostedConfig(env);
  if (!config) return null;
  try {
    const response = await fetch(config.base + "/v1/chat/completions", {
      method: "POST",
      headers: {
        authorization: `Bearer ${config.token}`,
        "content-type": "application/json",
        accept: "application/json"
      },
      redirect: "error",
      cache: "no-store",
      body: JSON.stringify({
        model: config.model,
        stream: false,
        temperature: 0.1,
        messages: payload.messages,
        response_format: payload.response_format
      })
    });
    if (!response.ok) return null;
    const result = await response.json();
    const content = result?.choices?.[0]?.message?.content;
    return typeof content === "string" && content.trim() ? content : null;
  } catch {
    return null;
  }
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
      const selfHosted = await selfHostedHealth(env);
      const cloudflareReady = Boolean(env.AI && typeof env.AI.run === "function");
      const activeProvider = selfHosted.ready
        ? "self-hosted-openai-compatible"
        : cloudflareReady ? "cloudflare-workers-ai" : null;
      return json({
        ok: Boolean(activeProvider),
        service: "streamiov-ai-worker",
        model: MODEL_ID,
        active_provider: activeProvider,
        providers: [
          { provider: "self-hosted-openai-compatible", ready: selfHosted.ready, model: selfHosted.model },
          { provider: "cloudflare-workers-ai", ready: cloudflareReady, model: MODEL_ID }
        ],
        authentication: "verified"
      });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/chat/completions") {
      return json({ error: { code: "method_not_allowed", message: "Method not allowed." } }, 405);
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
      // Prefer the explicitly configured Streamiov-owned model host. The
      // existing Workers AI binding remains the only configured fallback.
      const selfHostedContent = await selfHostedGenerate(env, payload);
      if (selfHostedContent) {
        return json({
          id: crypto.randomUUID(),
          object: "chat.completion",
          created: Math.floor(Date.now() / 1000),
          model: MODEL_ID,
          choices: [{ index: 0, message: { role: "assistant", content: selfHostedContent }, finish_reason: "stop" }]
        });
      }
      if (!env.AI || typeof env.AI.run !== "function") {
        return json({ error: { code: "inference_not_configured", message: "No self-hosted model endpoint or Workers AI binding is ready." } }, 503);
      }
      const aiInput = {
        messages: payload.messages,
        temperature: 0.1,
        chat_template_kwargs: { enable_thinking: false },
        max_tokens: MAX_OUTPUT_TOKENS
      };
      if (payload.response_format) aiInput.response_format = payload.response_format;
      let result;
      try {
        result = await env.AI.run(MODEL_ID, aiInput);
      } catch (error) {
        const detail = String((error && error.message) || error || "");
        if (!payload.response_format || !/json.?mode|json.?schema|response_format|structured output/i.test(detail)) throw error;
        delete aiInput.response_format;
        result = await env.AI.run(MODEL_ID, aiInput);
      }
      const content = extractModelText(result);
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
