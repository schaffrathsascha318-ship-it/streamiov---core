# Streamiov AI Worker

A separate Cloudflare Worker for Streamiov's server-side model inference. It is deliberately isolated from the homepage Worker and from the Chromebook development environment.

## Model and cost boundary

- Fixed model: `@cf/zai-org/glm-4.7-flash`.
- Cloudflare lists this model as hosted, with reasoning and function-calling support.
- Workers AI Free currently includes 10,000 Neurons per day. This is a real provider quota, not unlimited compute. When the allocation is exhausted, this Worker returns HTTP 429 and pauses requests until reset.
- No paid fallback, external model provider, automatic upgrade, or user-facing paid tier is configured.

Official references:
- https://developers.cloudflare.com/workers-ai/models/glm-4.7-flash/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/configuration/bindings/

## Security

- All routes require a bearer token of at least 32 characters, including the health endpoint.
- Store the token as a Cloudflare Worker secret; never commit it or put it in a frontend bundle.
- Requests are limited to 64 KiB, 24 messages, 12,000 characters per message, 48,000 prompt characters, and 4,096 output tokens.
- Only system/user/assistant messages are accepted. The model ID is fixed server-side.
- Prompts, responses, and tokens are not written to application logs.
- Only the Cloudflare AI binding is used for inference.

## Deploy

Use the Cloudflare account already authorized with Wrangler:

```bash
npx wrangler@4 secret put STREAMIOV_AI_WORKER_TOKEN --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc
npx wrangler@4 deploy --config infrastructure/cloudflare/streamiov-ai-worker/wrangler.jsonc
```

Create a high-entropy token (at least 32 characters) locally and enter it only at the Wrangler secret prompt. Keep the same value in the agent machine's `STREAMIOV_AI_WORKER_TOKEN` environment variable. Do not put it in GitHub source files.

Wrangler prints the deployed `workers.dev` URL. Use that URL as `STREAMIOV_MODEL_URL`.

## Client configuration

After deployment:

```bash
export STREAMIOV_MODEL_PROVIDER=cloudflare-workers-ai
export STREAMIOV_MODEL=@cf/zai-org/glm-4.7-flash
export STREAMIOV_MODEL_URL=https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev
export STREAMIOV_AI_WORKER_TOKEN='the-same-secret-entered-in-wrangler'
python -m ai --doctor
```

The agent CLI should report the worker and model as ready before running a task. Replace the example URL with the exact URL printed by Wrangler.

## Verification status

The Worker source and tests can be validated in GitHub Actions. This repository change does not deploy the Worker, create the Cloudflare secret, or prove that the user's Cloudflare account has the Workers AI binding enabled. A successful deployment and a real `--doctor` check are required before calling the service online.
