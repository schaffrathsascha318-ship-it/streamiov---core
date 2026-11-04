# StreamioV zero-spend implementation rules

**Status:** Product and engineering constraint from the owner.  
**Applies to:** AI, Studio, hosting, music, games, downloads, and operations.

## Budget rule

StreamioV must not require new spending or a third-party service provider to build or use its core features. StreamioV itself earns no revenue: no ads, subscriptions, paid tiers, sales, donations to StreamioV, paid gifts, platform commission, or payment collection. Build StreamioV's product modules in the project and operate core services on hardware already controlled by the owner. Do not add a paid API, subscription, commercial SDK, paid music catalogue, paid hosting tier, paid model endpoint, or automatic paid fallback. Never trigger an upgrade, purchase, or billable resource change automatically.

The implementation target is **zero additional cash outlay and no required hosted vendor**, using hardware and internet access already available to the owner. Electricity, an existing internet connection, equipment wear, and voluntary maintenance still have real costs; the project must not claim those are literally zero. A capability that needs newly purchased hardware or a paid service stays optional and is not required for the free product.

“Build it ourselves” applies to StreamioV's product logic and user experience: Regie, scene engine, media routing, music catalogue and rights records, game framework, task orchestration, and specialist workflows. It does not mean reimplementing operating-system APIs, media codecs, cryptography, or networking protocols from scratch. Use maintained open-source libraries locally where needed, check their licenses, and avoid requiring the library author's hosted service. A dependency's service is never the product's only path.

## Hosting and compute

- GitHub Pages can serve the static project homepage, documentation, and links to releases. It cannot run the persistent StreamioV backend, model, database, media relay, or WebSocket worker; Pages does not support server-side languages. Keep account data, login callbacks that need a secret, live events, and the Studio host off Pages. Pages use is also subject to GitHub's restrictions on SaaS-oriented/commercial hosting, so do not use it as StreamioV's hosted product service. See [GitHub Pages limitations](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) and [Pages site creation](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site).
- GitHub Actions can build and test the project, but jobs are finite and end when the workflow finishes; they are not an always-on server. GitHub documents standard hosted runner use as free for public repositories, while private repositories have plan quotas and additional use can be billed. Configure any CI use with spending/usage limits and never depend on Actions for runtime availability. See [GitHub Actions billing and usage](https://docs.github.com/en/actions/concepts/billing-and-usage).
- The homepage is an information and download entry point. Static Pages hosting cannot run the persistent core host; the backend must be separately self-hosted on existing owner-controlled hardware. If the current homepage provider is unavailable, the application must still run and the homepage can be self-hosted as a static site.
- Core services and the AI task worker must run locally or on already-owned/available hardware. The owner can choose an existing always-on computer as host; if it is offline, remote features pause and report that state clearly.
- Do not depend on a third-party cloud tier for core operation. An external service may be used only as an optional adapter selected by the owner; it must require no payment method, have an explicit quota stop, and have no upgrade or billable fallback.
- Prefer small, locally runnable, open-weight models and specialist roles sharing one local model. Each role gets a separate task contract and permissions; separate model copies are unnecessary unless testing demonstrates a need and existing hardware can support them.
- Network-requiring AI research may use public web pages when available, but it must degrade gracefully to manual links and cached, attributable notes. Never evade provider restrictions or scrape protected media.

## Studio and downloadable builds

- Keep the Studio as a downloadable local application. Camera, microphone, capture, scene composition, audio routing, and local encoding use the creator's device.
- Do not require OBS, a paid streaming relay, a paid plugin, or a hosted encoder.
- Use existing operating-system facilities and auditable, redistributable open-source components. Record licenses and bundle required components where their licenses allow it. The Studio itself must not require an external streaming relay, hosted encoder, plugin marketplace, login vendor, or music service to operate locally.
- An external destination such as TikTok still requires its own authorized connection. Do not represent this platform connection as owned by StreamioV or bypass its official access rules.
- If a device lacks an encoder, compatible driver, or enough compute, show the limitation and offer supported local options. Never silently switch to paid cloud encoding.

## Self-built instead of purchased

The rule is to implement free, auditable replacements before considering a purchase:

- **Release integrity:** Ed25519 signatures over the checksum manifests (`scripts/release-signing.mjs`), with a published public key and fingerprint. This costs nothing and needs no certificate authority. It is not a substitute for CA-backed Authenticode/notarisation; that paid option stays optional and is never bought automatically.
- **Audio proof:** a local RTMP listener plus `ffprobe` analysis (`scripts/stream-audio-check.py`) proves what the encoder actually sends, without a paid relay or test service.
- **Hardware evidence:** `scripts/collect-hardware-report.py` records OS, CPU, memory, tool versions, commit and installer hashes for each test device.
- **Streaming, AI and hosting:** core paths stay local or on already-owned hardware; external platforms and paid tiers are never required for the free product.

## Music research and playback

- The music player can be included in the free Studio, but StreamioV must not host or stream commercial catalogue recordings without documented rights for the exact usage (local playback, live broadcast, and stored replay are separate checks).
- Start with creator-submitted tracks, original StreamioV music, public-domain works whose status has been checked for the target territory, and tracks whose rightsholders grant the needed permissions at no charge.
- The research AI stores source URLs, access dates, territories, permitted uses, attribution requirements, evidence, and uncertainty. It labels results `cleared`, `restricted`, or `unknown`; it never treats absence of a claim as proof of permission.
- The catalogue must track composition, lyrics, performance, and sound-recording rights separately where present. Each approval records the rightsholder, grant basis, attribution, source title/publisher/section/access date, exact territory/use, zero cost, and human reviewer. For Germany the model is informed by UrhG §§ 15/19a (public uses), § 31 (usage rights can be restricted by use/territory/time), §§ 73/77 (performers), and § 85 (phonogram producers); these are research prompts, not an automated legal opinion. See the [official UrhG text](https://www.gesetze-im-internet.de/urhg/BJNR012730965.html).
- Lyrics/content policy is separate from rights: configurable age/content labels for sexual material, violence, hate, and political material. Apply published conduct rules consistently across political viewpoints; uncertain classification is flagged for human review.
- Until an age policy is implemented, explicit sexual content is blocked by default. Political content is reviewable, while left/right/mixed direction is descriptive metadata and never an automatic block. These are StreamioV policy settings, not legal conclusions.
- A license or legal status that is uncertain blocks inclusion until an authorized person resolves it. The AI is a research aid, not a legal decision-maker.

## Gifts and money

- StreamioV does not sell gifts, collect payments, take a commission, or process creator payouts.
- StreamioV-native gifts are free visual/event actions with no purchase, cash-out, or monetary conversion.
- TikTok-native gifts remain TikTok transactions governed by TikTok. StreamioV may display approved event metadata when officially available, but must not sell, redirect, or settle those transactions.

## Games and Game AI

- The Game AI should support multiple genres through scoped specialist workflows while sharing the existing local model where practical.
- Games must be original or have documented rights for each component and use. No copyrighted game binaries, art, music, names, or characters may be reused merely because they are easy to find online.
- Use the StreamioV vector mark, a skippable/reduced-motion intro/outro, and accurate credits. The shared branding is free to include and must not falsely imply ownership of third-party material.
- Existing first-draft assets and their local preview are in `games/branding/`.

## Graceful limits and cost checks

- Paid capabilities are disabled by default and cannot be activated through a model-generated task.
- Optional free integrations must show the provider, quota/availability limits, data sent, and a self-hosted or local alternative. On quota exhaustion, pause and explain; never upgrade or fall back to a paid provider.
- Before adding any dependency or operation, record whether it adds a license fee, mandatory account, usage charge, hosting charge, or payment processing fee. If any answer is yes or unknown, it cannot be a required path for the zero-spend product.
- Build and test workflows may prepare releases. The owner has authorized autonomous publication of finished, verified deliverables at the end of this project; that authorization does not include paid provisioning, purchases, or unapproved TikTok access.

## Product promise

The promise is: **StreamioV is free to use and StreamioV does not earn revenue from its users.** It is not a promise that internet access, electricity, existing equipment, legal music clearance, or every third-party platform has no cost. No third-party charge may be routed through StreamioV or described as a StreamioV fee.
