# Cloudflare R2 policy — prohibited

**Decision: Streamiov must not use Cloudflare R2.** This prohibition applies to
production, development, CI, previews, backups, media storage, and fallback paths.

- Do not create, bind, enable, or access an R2 bucket.
- Do not add R2 SDK calls, R2Bucket bindings, env.R2 access, Wrangler R2
  commands, or a service that silently falls back to R2.
- Do not treat a provider free tier, promotional allowance, GitHub Actions, or a
  GitHub repository as proof that R2 is permanently free. Usage can exceed
  allowances and incur charges; GitHub cannot make a Cloudflare resource free.
- Use existing GitHub repository assets/releases or already configured
  non-R2 storage only where licensing, size, privacy, retention, and operational
  requirements permit. Do not copy secrets, private user data, or licensed media
  into a public repository or release artifact.
- Any future policy change requires a new explicit owner decision and a verified
  cost model. Until then, R2 remains disabled and forbidden.

The offline Cloudflare configuration verifier enforces this rule against
executable Cloudflare configuration, deployment workflows, scripts, and Worker
source. It does not contact Cloudflare or claim anything about remote account
resources; those must remain untouched.
