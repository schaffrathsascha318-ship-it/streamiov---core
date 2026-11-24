# Streamiov AI Worker

A separate Cloudflare Worker for Streamiov's server-side model inference. It is deliberately isolated from the homepage Worker and from the Chromebook development environment.

## Model and cost boundary

- The Worker now supports an explicitly configured Streamiov-controlled, self-hosted model endpoint first.
- The self-hosted endpoint must be HTTPS and bearer-authenticated. It can be an Ollama-backed OpenAI-compatible gateway from `infrastructure/ai-model-runtime`.
- If the self-hosted endpoint is absent or unavailable, the existing pinned Workers AI model `@cf/zai-org/glm-4.7-flash` remains the configured fallback.
- Workers AI Free has a real provider quota. When its allocation is exhausted, the Worker returns HTTP 429; it does not activate paid inference or upgrade billing.
- The self-hosted model runs on hardware controlled by Streamiov. A Cloudflare Worker is the control plane and secure router; it does not load multi-gigabyte model weights into the Worker runtime.

## Configure self-hosted inference

Deploy the model gateway described in [the self-hosted runtime guide](../../ai-model-runtime/README.md) on a separate machine with sufficient RAM/storage (and an optional compatible GPU). Do not use the Chromebook development environment as a production model host.

Set these variables/secrets on the Cloudflare Worker:

- Variable `STREAMIOV_SELF_HOSTED_MODEL_URL`: HTTPS hostname of the authenticated model gateway, e.g. `https://model.example.com`.
- Variable `STREAMIOV_SELF_HOSTED_MODEL`: exact model name exposed by the gateway, e.g. `qwen2.5-coder:7b`.
- Secret `STREAMIOV_SELF_HOSTED_MODEL_TOKEN`: same high-entropy bearer token configured on the gateway.

The Worker probes the self-hosted `/health` endpoint and tries it before Workers AI. If the self-hosted service is unavailable, the existing Workers AI binding is used. To disable that fallback entirely, remove/disable the Workers AI binding only after a self-hosted-only deployment has been verified; do not make that production change as part of this code-only change.

## Security

- All Worker routes require the existing bearer token of at least 32 characters, including health.
- The self-hosted endpoint has its own bearer secret. It is never returned in health responses or application logs.
- Self-hosted endpoint URLs must use HTTPS and cannot contain credentials, query strings, fragments, or custom ports.
- Requests are limited to 64 KiB, 24 messages, 32,000 characters per message, and 48,000 prompt characters.
- Only system/user/assistant messages are accepted. The Worker model identifier remains pinned at the public gateway boundary.
- Prompts, responses, and tokens are not written to application logs.

## Deploy

The deployment workflow remains manual and owner-approved. After configuring the self-hosted variables/secrets, deploy the Worker using the existing process:

```bash
npx wrangler@4 secret put STREAMIOV_SELF_HOSTED_MODEL_TOKEN --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc
npx wrangler@4 deploy --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc
```

Keep the existing `STREAMIOV_AI_WORKER_TOKEN` secret configured. Do not commit secrets or put them in a frontend bundle.

## Client configuration

The AI Chief can use a direct self-hosted provider chain. Configure the GitHub Actions repository variable `STREAMIOV_MODEL_PROVIDERS` as:

```text
self-hosted-openai-compatible,cloudflare-workers-ai
```

Also set repository variables `STREAMIOV_SELF_HOSTED_MODEL_URL` and `STREAMIOV_SELF_HOSTED_MODEL`, and secret `STREAMIOV_SELF_HOSTED_MODEL_TOKEN`. The self-hosted model is tried first; the existing Workers AI gateway is used only if it is explicitly listed later in the chain.

For a direct local CLI connection to the HTTPS gateway:

```bash
export STREAMIOV_MODEL_PROVIDERS=self-hosted-openai-compatible
export STREAMIOV_SELF_HOSTED_MODEL=qwen2.5-coder:7b
export STREAMIOV_SELF_HOSTED_MODEL_URL=https://model.example.com
export STREAMIOV_SELF_HOSTED_MODEL_TOKEN='the-same-secret-entered-on-the-model-host'
python -m ai --doctor
```

## Verification status

The self-hosted gateway, Python provider, Cloudflare Worker routing, and their tests are part of the repository source. They are not proof that a production model host has been provisioned or that the new Worker code has been deployed.

A successful `/health` check proves that the configured model is listed. A real inference request must also succeed before calling the runtime operational. The existing production Worker remains on its last deployed revision until a separately owner-approved deployment is completed.

The Chromebook development host previously had only about 213 MiB of available RAM, which is not sufficient for the proposed 7B model. The self-hosted runtime therefore requires a separate machine with adequate resources. No paid GPU instance, model-provider billing, or Cloudflare production deployment is activated by this PR.
