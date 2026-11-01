"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { MediaRuntime, MediaRuntimeError, STATES } = require("../studio/media-runtime");

function fixture({ active = true } = {}) {
  const calls = [];
  const runtime = new MediaRuntime({
    compositor: { async start() { calls.push("compositor.start"); }, async stop() { calls.push("compositor.stop"); } },
    mixer: { async start() { calls.push("mixer.start"); }, async stop() { calls.push("mixer.stop"); } },
    encoder: { async start() { calls.push("encoder.start"); }, async stop() { calls.push("encoder.stop"); } },
    output: {
      async connect(args) { calls.push(["output.connect", args]); },
      async isActive() { return active; },
      async disconnect() { calls.push("output.disconnect"); },
    },
  });
  return { runtime, calls };
}

test("LIVE requires positive transport confirmation, not merely connect success", async () => {
  const { runtime } = fixture({ active: false });
  await runtime.startPreview({ scenes: [] });
  const state = await runtime.startOutput({
    destination: "rtmps://live.example.test/app",
    streamKey: "secret-stream-key-123",
    profile: { width: 1280, height: 720, fps: 30 },
  });
  assert.equal(state.state, STATES.CONNECTING);
  assert.equal(state.live, false);
  assert.equal(state.outputConfirmed, false);
  runtime.confirmOutputActive(true);
  assert.equal(runtime.snapshot().live, true);
});

test("stream keys are passed only to the output adapter and never enter snapshots", async () => {
  const { runtime, calls } = fixture();
  await runtime.startPreview({});
  const secret = "never-log-this-stream-key";
  const state = await runtime.startOutput({
    destination: "rtmps://live.example.test/app",
    streamKey: secret,
    profile: {},
  });
  assert.equal(state.live, true);
  assert.equal(JSON.stringify(state).includes(secret), false);
  const connect = calls.find(item => Array.isArray(item) && item[0] === "output.connect");
  assert.equal(connect[1].streamKey, secret);
});

test("rejects non-RTMP destinations and credentials embedded in URLs", async () => {
  const { runtime } = fixture();
  await runtime.startPreview({});
  await assert.rejects(
    runtime.startOutput({ destination: "https://example.test", streamKey: "12345678", profile: {} }),
    error => error instanceof MediaRuntimeError && error.code === "INVALID_DESTINATION",
  );
  await assert.rejects(
    runtime.startOutput({ destination: "rtmps://user:pass@example.test/app", streamKey: "12345678", profile: {} }),
    error => error instanceof MediaRuntimeError && error.code === "INVALID_DESTINATION",
  );
});

test("output interruption immediately removes LIVE status", async () => {
  const { runtime } = fixture();
  await runtime.startPreview({});
  await runtime.startOutput({
    destination: "rtmp://live.example.test/app",
    streamKey: "12345678",
    profile: {},
  });
  assert.equal(runtime.snapshot().live, true);
  runtime.outputLost();
  assert.equal(runtime.snapshot().state, STATES.RECONNECTING);
  assert.equal(runtime.snapshot().live, false);
});

test("stop shuts down adapters and returns to idle", async () => {
  const { runtime, calls } = fixture();
  await runtime.startPreview({});
  await runtime.startOutput({
    destination: "rtmps://live.example.test/app",
    streamKey: "12345678",
    profile: {},
  });
  const result = await runtime.stop();
  assert.equal(result.state, STATES.IDLE);
  assert.equal(result.live, false);
  assert.ok(calls.includes("output.disconnect"));
  assert.ok(calls.includes("encoder.stop"));
  assert.ok(calls.includes("compositor.stop"));
  assert.ok(calls.includes("mixer.stop"));
});
