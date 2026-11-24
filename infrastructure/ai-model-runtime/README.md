# Streamiov self-hosted model runtime

This is the first deployable inference service for the Streamiov Core model
router. It runs an Ollama model on hardware you control and exposes only a
small bearer-authenticated OpenAI-compatible gateway. Ollama itself is never
published to the host network.

## Important architecture boundary

A Cloudflare Worker cannot load and host multi-gigabyte model weights as part
of its normal Worker runtime. The Streamiov Core remains the control plane:
agent orchestration, provider selection, health reporting, and secure routing.
The model process runs on a separate machine/container host that you control
and is reached over an HTTPS endpoint (for example, through an existing
Cloudflare Tunnel). This repository does not claim that a model is already
deployed or running.

The Chromebook development environment is not treated as a production model
host. Deploy this service only on a machine with enough RAM/storage (and a
compatible GPU if desired).

## Start the runtime

1. Install Docker Engine and the Docker Compose plugin on the chosen model host.
2. Copy `.env.example` to `.env` and replace the placeholder token with a
   unique random secret of at least 32 characters. Never commit `.env`.
3. Start the services:

   ```sh
   docker compose up -d --build
   docker compose exec ollama ollama pull "${STREAMIOV_OLLAMA_MODEL:-qwen2.5-coder:7b}"
   ```

4. Check the local authenticated health endpoint:

   ```sh
   curl -H "Authorization: Bearer $STREAMIOV_MODEL_GATEWAY_TOKEN" http://127.0.0.1:8080/health
   ```

The gateway binds to host loopback only. Do not publish port 8080 directly to
the public internet. Connect an existing Cloudflare Tunnel to
`http://127.0.0.1:8080`, protect its hostname with HTTPS, and keep the bearer
token configured in the Streamiov Core/AI Chief secret store.

## Connect the AI Chief

Set these repository variables/secrets for the autonomous workflow:

- Variable `STREAMIOV_MODEL_PROVIDERS`:
  `self-hosted-openai-compatible,cloudflare-workers-ai`
- Variable `STREAMIOV_SELF_HOSTED_MODEL_URL`: the HTTPS tunnel origin, e.g.
  `https://model.example.com` (hostname only; no path, query, or port).
- Variable `STREAMIOV_SELF_HOSTED_MODEL`: the exact Ollama model name, e.g.
  `qwen2.5-coder:7b`.
- Secret `STREAMIOV_SELF_HOSTED_MODEL_TOKEN`: same random token as the gateway.

The self-hosted model is tried first. Cloudflare Workers AI is only attempted
if it is explicitly present later in the configured provider list. To run
self-hosted-only, set the provider list to
`self-hosted-openai-compatible`; the workflow will not silently add another
provider. The existing Cloudflare AI gateway remains unchanged.

## Resource notes

Model size, RAM, CPU/GPU support and inference speed depend on the chosen
machine and model quantization. Do not assume the 7B model fits a low-memory
device. Start with a smaller model on constrained hardware and verify with
`python -m ai --doctor` after configuring the provider. A successful health
check proves the configured model is listed; a successful real task is still
required to prove inference works end to end.

## Security

- Ollama is only reachable inside the Docker network.
- The gateway requires a bearer token of at least 32 characters.
- The host port binds to 127.0.0.1; use a TLS tunnel rather than public port
  exposure.
- Prompts, completions, and authorization values are not written to logs.
- Request size, prompt size, message count, and concurrent inference are
  bounded.
- No paid model provider, GPU instance, or billing service is activated.
