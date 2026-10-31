import test from "node:test";
import assert from "node:assert/strict";
import worker from "../infrastructure/cloudflare/streamiov-ai-worker/src/index.mjs";

const TOKEN = "streamiov-test-token-with-more-than-32-characters";
const MODEL = "@cf/zai-org/glm-4.7-flash";
const base = "https://streamiov-ai.test";

function env(overrides = {}) {
  return {
    STREAMIOV_AI_WORKER_TOKEN: TOKEN,
    AI: {
      run: async (model, options) => ({
        response: JSON.stringify({ final: "AI worker responded" }),
        model,
        received: options.messages.length
      })
    },
    ...overrides
  };
}

function authHeaders(extra = {}) {
  return { authorization: `Bearer ${TOKEN}`, ...extra };
}

function chatRequest(payload, headers = authHeaders()) {
  return new Request(base + "/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(payload)
  });
}

test("health endpoint requires token and reports pinned model", async () => {
  const denied = await worker.fetch(new Request(base + "/health"), env());
  assert.equal(denied.status, 401);

  const response = await worker.fetch(
    new Request(base + "/health", { headers: authHeaders() }),
    env()
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.equal(body.model, MODEL);
  assert.equal(body.authentication, "verified");
});

test("chat endpoint proxies only the fixed model and returns OpenAI shape", async () => {
  let receivedModel;
  let receivedOptions;
  const runtime = env({
    AI: {
      run: async (model, options) => {
        receivedModel = model;
        receivedOptions = options;
        return { response: '{"final":"completed"}' };
      }
    }
  });
  const response = await worker.fetch(
    chatRequest({ model: MODEL, messages: [{ role: "user", content: "Build a test" }] }),
    runtime
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.object, "chat.completion");
  assert.equal(body.model, MODEL);
  assert.equal(body.choices[0].message.content, '{"final":"completed"}');
  assert.equal(receivedModel, MODEL);
  assert.equal(receivedOptions.max_tokens, 4096);
});

test("rejects invalid bearer tokens and missing secret configuration", async () => {
  const invalid = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "hello" }] }, { authorization: "Bearer wrong" }),
    env()
  );
  assert.equal(invalid.status, 401);

  const missing = await worker.fetch(
    new Request(base + "/health", { headers: authHeaders() }),
    env({ STREAMIOV_AI_WORKER_TOKEN: "" })
  );
  assert.equal(missing.status, 503);
});

test("validates message roles, model id, and streaming mode", async () => {
  const invalidRole = await worker.fetch(
    chatRequest({ messages: [{ role: "tool", content: "no" }] }),
    env()
  );
  assert.equal(invalidRole.status, 400);

  const wrongModel = await worker.fetch(
    chatRequest({ model: "@cf/another/model", messages: [{ role: "user", content: "no" }] }),
    env()
  );
  assert.equal(wrongModel.status, 400);

  const streaming = await worker.fetch(
    chatRequest({ stream: true, messages: [{ role: "user", content: "no" }] }),
    env()
  );
  assert.equal(streaming.status, 400);
});

test("enforces request body and prompt limits before inference", async () => {
  const oversized = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "x".repeat(70_000) }] }),
    env()
  );
  assert.equal(oversized.status, 413);

  let called = false;
  const tooMany = await worker.fetch(
    chatRequest({ messages: Array.from({ length: 25 }, () => ({ role: "user", content: "x" })) }),
    env({ AI: { run: async () => { called = true; return { response: "no" }; } } })
  );
  assert.equal(tooMany.status, 400);
  assert.equal(called, false);
});

test("pauses instead of falling back to paid inference when daily quota is exhausted", async () => {
  const response = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "hello" }] }),
    env({ AI: { run: async () => { throw new Error("daily neuron quota limit exceeded"); } } })
  );
  assert.equal(response.status, 429);
  const body = await response.json();
  assert.equal(body.error.code, "daily_ai_limit_reached");
  assert.match(body.error.message, /free daily AI allocation/);
});

test("unknown routes and unavailable AI bindings fail closed", async () => {
  const notFound = await worker.fetch(
    new Request(base + "/anything", { headers: authHeaders() }),
    env()
  );
  assert.equal(notFound.status, 404);

  const unavailable = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "hello" }] }),
    env({ AI: null })
  );
  assert.equal(unavailable.status, 503);
});
