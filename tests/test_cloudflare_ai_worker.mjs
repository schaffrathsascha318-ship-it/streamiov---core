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

test("chat endpoint supports legacy response shape and returns OpenAI shape", async () => {
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
  assert.deepEqual(receivedOptions.chat_template_kwargs, { enable_thinking: false });
});

test("chat forwards JSON mode to Workers AI and falls back if the model rejects it", async () => {
  const calls = [];
  const runtime = env({
    AI: {
      run: async (model, options) => {
        calls.push(JSON.parse(JSON.stringify(options)));
        if (calls.length === 1) throw new Error("JSON Mode couldn't be met");
        return { response: '{"final":"fallback succeeded"}' };
      }
    }
  });
  const response = await worker.fetch(
    chatRequest({
      model: MODEL,
      messages: [{ role: "user", content: "Return JSON" }],
      response_format: { type: "json_object" }
    }),
    runtime
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.choices[0].message.content, '{"final":"fallback succeeded"}');
  assert.deepEqual(calls[0].response_format, { type: "json_object" });
  assert.equal("response_format" in calls[1], false);
});

test("chat rejects unsupported response formats before inference", async () => {
  let calls = 0;
  const response = await worker.fetch(
    chatRequest({
      model: MODEL,
      messages: [{ role: "user", content: "Return JSON" }],
      response_format: { type: "json_schema", schema: {} }
    }),
    env({
      AI: {
        run: async () => {
          calls += 1;
          return { response: "{}" };
        }
      }
    })
  );
  assert.equal(response.status, 400);
  assert.equal((await response.json()).error.code, "unsupported-response-format");
  assert.equal(calls, 0);
});

test("chat endpoint extracts OpenAI-style choices returned by Workers AI", async () => {
  const response = await worker.fetch(
    chatRequest({ model: MODEL, messages: [{ role: "user", content: "Say hello" }] }),
    env({
      AI: {
        run: async () => ({
          choices: [{ message: { role: "assistant", content: "STREAMIOV-OK" } }]
        })
      }
    })
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.choices[0].message.content, "STREAMIOV-OK");
});

test("chat endpoint joins text parts from structured choice content", async () => {
  const response = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "Say hello" }] }),
    env({
      AI: {
        run: async () => ({
          choices: [{ message: { content: [{ type: "text", text: "STREAMIOV" }, { type: "text", text: "-OK" }] } }]
        })
      }
    })
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.choices[0].message.content, "STREAMIOV-OK");
});

test("empty model result remains an explicit gateway error", async () => {
  const response = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "hello" }] }),
    env({ AI: { run: async () => ({}) } })
  );
  assert.equal(response.status, 502);
  const body = await response.json();
  assert.equal(body.error.code, "empty_model_response");
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

test("allows bounded multi-file agent context above the former 12 KB message limit", async () => {
  let called = false;
  const response = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "x".repeat(20_000) }] }),
    env({ AI: { run: async () => { called = true; return { response: "accepted" }; } } })
  );
  assert.equal(response.status, 200);
  assert.equal(called, true);
});

test("accepts a message exactly at the 32 KB per-message ceiling", async () => {
  let called = false;
  const response = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "x".repeat(32_000) }] }),
    env({ AI: { run: async () => { called = true; return { response: "accepted" }; } } })
  );
  assert.equal(response.status, 200);
  assert.equal(called, true);
});

test("enforces per-message, aggregate prompt, and request body limits before inference", async () => {
  const oversizedBody = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "x".repeat(70_000) }] }),
    env()
  );
  assert.equal(oversizedBody.status, 413);

  let called = false;
  const tooManyMessages = await worker.fetch(
    chatRequest({ messages: Array.from({ length: 25 }, () => ({ role: "user", content: "x" })) }),
    env({ AI: { run: async () => { called = true; return { response: "no" }; } } })
  );
  assert.equal(tooManyMessages.status, 400);
  assert.equal(called, false);

  const tooLongMessage = await worker.fetch(
    chatRequest({ messages: [{ role: "user", content: "x".repeat(32_001) }] }),
    env({ AI: { run: async () => { called = true; return { response: "no" }; } } })
  );
  assert.equal(tooLongMessage.status, 400);
  assert.equal(called, false);

  const tooLargePrompt = await worker.fetch(
    chatRequest({ messages: [
      { role: "user", content: "x".repeat(25_000) },
      { role: "assistant", content: "y".repeat(24_000) }
    ] }),
    env({ AI: { run: async () => { called = true; return { response: "no" }; } } })
  );
  assert.equal(tooLargePrompt.status, 400);
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


test("prefers the authenticated self-hosted model before Workers AI", async () => {
  const originalFetch = globalThis.fetch;
  let receivedUrl = "";
  let receivedAuthorization = "";
  let receivedPayload;
  let workersAiCalled = false;
  globalThis.fetch = async (url, options) => {
    receivedUrl = String(url);
    receivedAuthorization = options.headers.authorization;
    receivedPayload = JSON.parse(options.body);
    return new Response(JSON.stringify({
      choices: [{ message: { role: "assistant", content: "SELF-HOSTED-OK" } }]
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    const response = await worker.fetch(
      chatRequest({
        model: MODEL,
        messages: [{ role: "user", content: "Build Streamiov" }],
        response_format: { type: "json_object" }
      }),
      env({
        STREAMIOV_SELF_HOSTED_MODEL_URL: "https://model.example.com",
        STREAMIOV_SELF_HOSTED_MODEL_TOKEN: TOKEN,
        STREAMIOV_SELF_HOSTED_MODEL: "qwen2.5-coder:7b",
        AI: { run: async () => { workersAiCalled = true; return { response: "fallback" }; } }
      })
    );
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.choices[0].message.content, "SELF-HOSTED-OK");
    assert.equal(receivedUrl, "https://model.example.com/v1/chat/completions");
    assert.equal(receivedAuthorization, `Bearer ${TOKEN}`);
    assert.equal(receivedPayload.model, "qwen2.5-coder:7b");
    assert.deepEqual(receivedPayload.response_format, { type: "json_object" });
    assert.equal(workersAiCalled, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("falls back to the existing Workers AI binding when self-hosted inference is unavailable", async () => {
  const originalFetch = globalThis.fetch;
  let workersAiCalled = false;
  globalThis.fetch = async () => new Response("unavailable", { status: 503 });
  try {
    const response = await worker.fetch(
      chatRequest({ model: MODEL, messages: [{ role: "user", content: "Fallback test" }] }),
      env({
        STREAMIOV_SELF_HOSTED_MODEL_URL: "https://model.example.com",
        STREAMIOV_SELF_HOSTED_MODEL_TOKEN: TOKEN,
        STREAMIOV_SELF_HOSTED_MODEL: "qwen2.5-coder:7b",
        AI: { run: async () => { workersAiCalled = true; return { response: "WORKERS-AI-FALLBACK" }; } }
      })
    );
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.choices[0].message.content, "WORKERS-AI-FALLBACK");
    assert.equal(workersAiCalled, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("health reports self-hosted model as active when it is ready", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    ok: true, model: "qwen2.5-coder:7b"
  }), { status: 200, headers: { "content-type": "application/json" } });
  try {
    const response = await worker.fetch(
      new Request(base + "/health", { headers: authHeaders() }),
      env({
        STREAMIOV_SELF_HOSTED_MODEL_URL: "https://model.example.com",
        STREAMIOV_SELF_HOSTED_MODEL_TOKEN: TOKEN,
        STREAMIOV_SELF_HOSTED_MODEL: "qwen2.5-coder:7b"
      })
    );
    const body = await response.json();
    assert.equal(body.ok, true);
    assert.equal(body.active_provider, "self-hosted-openai-compatible");
    assert.equal(body.providers[0].ready, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("rejects an invalid self-hosted endpoint configuration and uses no remote request", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("must not be called"); };
  try {
    const response = await worker.fetch(
      chatRequest({ messages: [{ role: "user", content: "Safe fallback" }] }),
      env({
        STREAMIOV_SELF_HOSTED_MODEL_URL: "http://model.example.com",
        STREAMIOV_SELF_HOSTED_MODEL_TOKEN: TOKEN,
        AI: { run: async () => ({ response: "WORKERS-AI-SAFE" }) }
      })
    );
    assert.equal(response.status, 200);
    assert.equal((await response.json()).choices[0].message.content, "WORKERS-AI-SAFE");
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});


test("rejects loopback and IP-literal self-hosted model endpoints", async () => {
  const originalFetch = globalThis.fetch;
  let called = false;
  globalThis.fetch = async () => { called = true; throw new Error("must not be called"); };
  try {
    for (const endpoint of ["https://127.0.0.1", "https://192.168.1.10", "https://localhost"]) {
      const response = await worker.fetch(
        chatRequest({ messages: [{ role: "user", content: "No SSRF" }] }),
        env({
          STREAMIOV_SELF_HOSTED_MODEL_URL: endpoint,
          STREAMIOV_SELF_HOSTED_MODEL_TOKEN: TOKEN,
          AI: { run: async () => ({ response: "SAFE" }) }
        })
      );
      assert.equal(response.status, 200);
    }
    assert.equal(called, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
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
