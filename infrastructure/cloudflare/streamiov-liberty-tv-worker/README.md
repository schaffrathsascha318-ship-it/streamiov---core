# Streamiov Liberty TV – Core Worker

This is a separate Cloudflare Worker for the second Streamiov website. It serves
its own static site through the Worker Assets binding and exposes a non-sensitive
`GET /healthz` endpoint. It does not modify or deploy the existing
`streamiov.pages.dev` Pages project and does not reuse the AI Worker.

## Local verification

From the repository root:

```sh
npx wrangler@4 dev --config infrastructure/cloudflare/streamiov-liberty-tv-worker/wrangler.jsonc
```

Check `/` and `/healthz` locally. The Worker adds baseline browser security
headers to both static and health responses.

## Deployment boundary

No custom domain, DNS record, production route, secret, or Cloudflare resource
is created by this source change. The Worker is not live until an owner-approved
deployment is performed and its route/domain is configured. Do not use the
existing homepage deployment workflow for this Worker; that workflow targets
the existing Pages project named `streamiov`.

The current page is an initial project landing page. It does not claim that
accounts, live streaming, video hosting, or a backend API are implemented.
