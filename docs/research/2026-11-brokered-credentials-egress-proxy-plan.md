# Proposed plan: brokered model credentials at the egress container (ADR-003 follow-up 2)

- **Status:** Proposed. Not accepted, not implemented, and not permission to change the devcontainer, the egress container, `sandbox.py` or any test.
- **Date:** 2026-11-17 (Europe/Madrid). Updated 2026-11-19: Codex sandbox as second reference, DNS side-channel risk. Updated 2026-11-20: broker-as-target risk (LiteLLM CVE-2026-40217). Updated 2026-11-22: appendix on prompt content and provider routes (Dragos canary study, OpenRouter off-boarding).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-brokered-credentials-egress-proxy-plan.md`. If accepted, the decision goes in a new ADR that amends ADR-003's follow-up list. ADR-003 itself stays Accepted and unchanged.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** [ADR-003](../adr/ADR-003-sandbox-backends.md) follow-ups 2 and 8; [orca self-rollout plan](2026-11-orca-self-rollout-plan.md), which parks follow-up 2 because it "needs registries, vendor accounts or money".

## Why now

The model credential sits inside the agent container today. `devcontainer.json` passes `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) from the host, and `sandbox.py` records `credential_mode: env`. Anything that runs in the container can read it. Recent incidents show attackers hunt exactly these keys: Railway (Oct 2026) and the wave against infra providers reported on 16 Nov.

The orca plan assumed brokered credentials need a vendor. A local, Apache-2.0 example now exists. Prime Radiant's external sandboxes (Simon Willison, 16 Nov 2026) run a host-side proxy that swaps a placeholder header for the real secret, only for allow-listed origins and methods. The guest holds only the placeholder. Source read: the blog post in full. Code, protocol spec and conformance tests not read.

## Evidence and baseline

- **Documented elsewhere (post, read):** placeholder in `guestEnv`; proxy rule per origin with `header`, `placeholder`, `secretEnv` and `prefix`; secret read from the host process environment; proxy CA exposed to the guest; direct connections blocked. Stated limit: an allowed host can echo the credential back.
- **Harness (code read at `origin/main` `aa51447`, not executed):** two-container Compose design from ADR-003. The `egress` service owns the network namespace and the iptables allowlist. The agent service has no NET_ADMIN. `CREDENTIAL_VARIABLES` in `sandbox.py` lists the two variables above.
- **ADR-003 rejected a general HTTP(S) proxy** as the egress point because Gradle, Maven and Node's built-in `fetch` ignore proxy variables. This plan does not reverse that. It proxies only the model API host. All other traffic keeps today's transparent rules.
- **Second reference design (added 2026-11-19, post read, code not read):** OpenAI's "Inside the Codex sandbox" (18 Nov 2026, https://openai.com/index/inside-the-codex-sandbox). Codex runs a domain-filtering proxy outside the sandbox and blocks direct connections at the OS layer, so tools that ignore proxy variables fail closed. The proxy decides on the hostname before any DNS lookup, deny rules beat allow rules, and unmatched hosts pause for approval. It filters only. It does not swap credentials, so it supports option B's placement but not its header swap. Vendor description of its own product, not independently tested.
- **Not verified:** whether Claude Code reaches the model API through a base-URL override when it authenticates with an OAuth token rather than an API key. WP0 must answer this first.

## Options

- **A. Keep `env` (status quo).** No work. The key stays readable in the container.
- **B. Credential-replacing reverse proxy for the model API only, in the `egress` service.** The agent points at a local base URL with a placeholder key. The proxy adds the real header and forwards to the one upstream. Secret lives only in the `egress` service environment.
- **C. Adopt the external-sandbox servers as a backend.** Gives the proxy and a VM boundary. Experimental and unaudited by its authors, and Claude Code's Read and Edit tools would still run outside the sandbox. Belongs with follow-up 7 under its own ADR, not here.

Proposed: B, if WP0 passes. Otherwise stay on A and record why.

## Work packages

| WP | Scope | Depends on | Acceptance evidence |
|---|---|---|---|
| WP0 | Spike, no repo change: confirm the agent CLI works through a base-URL override with API key and with OAuth token. Note which headers carry the credential. | none | Short note in this file with CLI version, commands run and results. Stop if neither mode works. |
| WP1 | Design note: reverse-proxy shape (one upstream, fixed path prefix, header swap, no body rewrite), where the secret is mounted, logging without secrets. Also state whether the proxy resolves DNS for anything other than the one upstream (Codex resolves only after the allow decision). | WP0 | Reviewed design section added here. |
| WP2 | Implement the proxy in `egress` (stdlib Python, like the engine). Agent service gets the placeholder and base URL only. | WP1, maintainer acceptance | Tests: request with placeholder reaches upstream with real header; any other host or path is refused; secret absent from the agent container environment, filesystem and logs. |
| WP3 | Evidence: `credential_mode: brokered` when the agent sees only the placeholder and the egress service publishes that it brokers. Never name the credential. | WP2 | `receipt` shows `brokered`; old receipts unchanged; `sandbox.py` still understates when it cannot see proof. |
| WP4 | Docs: ADR amending follow-up 2, README and devcontainer comments. | WP3 | Docs reviewed in the same PR. |

## Risks

- The upstream echoes the credential in an error body. Mitigation: strip known credential headers from responses and log bodies only on error, redacted.
- The agent CLI changes its auth flow. Mitigation: WP0 records versions; a doctor check fails closed back to `env` with a visible warning, never silently.
- A second secret path appears (for example a GitHub token) and someone extends the proxy ad hoc. Each new origin needs its own reviewed rule.
- DNS as a side channel. If the agent container can still resolve arbitrary names, data can leave in hostnames even with the key brokered. Mitigation: WP1 records today's DNS path through `egress`; any change is a separate reviewed item.
- The broker becomes the target. CISA added LiteLLM CVE-2026-40217 to KEV on 18 Nov 2026 (The Hacker News, 19 Nov). The vendor advisory GHSA-wxxx-gvqv-xp7p says a guardrail test endpoint ran user Python in a home-made sandbox that could be escaped, giving code execution in the proxy process, which runs as root in the default Docker image. It needs a proxy-admin credential by default. Fixed in 1.83.10 or later. Mitigation for this plan: WP1 states that the broker has no admin, test or plugin endpoint that runs code, runs as a non-root user, and holds only the model secret. Advisory and news read; LiteLLM code not read. The harness does not use LiteLLM today as far as the docs show.
- Brokering hides the key but not its use. A compromised agent can still spend through the proxy. Rate or budget limits are out of scope here.

## Rollback

Unset the base URL and placeholder, pass the real variable again as today. `credential_mode` returns to `env`. No data migration.

## Pending human decisions

1. Accept option B for WP0 to start, or keep the status quo.
2. Whether OAuth-token users are in scope, or API-key only for a first version.
3. Whether a budget limit at the proxy should become its own follow-up.

## Appendix, 2026-11-22: what the prompt carries and where it goes

- **Status:** Proposed addition to this plan, same rules as above. It authorizes no change to `init-firewall.sh`, guardrails, hooks or tests, and no new account.

### Why

Brokering hides the model key. It does nothing about the other secrets an agent reads and sends as context, and it cannot tell whether a provider keeps or leaks prompts. New evidence says providers do.

- Dragos (HD Moore, 19 Nov 2026, https://www.dragos.com/blog/ai-supply-chain-security-canary-tokens, read in full) seeded about two million prompts with unique AWS keys, hostnames and URLs from July to November. It reports three breached inference providers, some stolen requests flagged Zero Data Retention (ZDR), keys tested within hours in some cases, and marketplace sellers reading prompts through request logging. Vendor write-up. A critique (flyingpenguin, 21 Nov) shows at least one timeline claim is wrong. The core finding is confirmed for Phala by Phala's own report (10 Nov).
- OpenRouter (22 Nov 2026, https://openrouter.ai/blog/announcements/data-processing-incidents-on-inference-providers/, read) off-boarded three providers and removed 125 endpoints from ZDR eligibility.
- Together AI (21 Nov 2026, read) says an AI coding agent committed a credential to a public repository, which exposed stored prompt samples. That is the harness's own failure class.
- Dragos's advice: pick upstream providers yourself, avoid reseller marketplaces, seed your own canary credential in the context agents already send, and use secret filtering knowing it misses data not shaped like a key. A ZDR flag binds only the first hop.

### Baseline (config read at the working tree on `release/0.31.0`, not executed)

- **Documented capability:** `init-firewall.sh` allows `api.anthropic.com` and `statsig.anthropic.com` as model hosts, plus GitHub hosts and anything in `HARNESS_FIREWALL_ALLOW`. In the container path the agent reaches one first-party model provider by default.
- **Gap:** a router or marketplace host can be added through `HARNESS_FIREWALL_ALLOW` with no recorded decision. Codex and OpenCode agent definitions ship in the payload. Which model hosts they call outside the container was not checked.
- **Documented capability:** `guardrails.core.conf` blocks writing private key blocks and AWS access key ids, in edits and at pre-commit. It covers writes. Nothing in the docs covers secrets the agent reads, for example `.env` files or command output, before they go to the model. Whether the hooks see read-tool calls at all was not checked.
- **Already covered elsewhere:** `2026-11-agent-sdlc-landscape.md` lists a test for exfiltration through an allowlisted host. That checks the agent leaking data. It does not detect the provider reading prompts.

### Options

- **A2. Status quo.** Rely on the default allowlist and the write guardrails. ZDR or provider privacy settings stay undocumented as a control.
- **B2. Written provider route policy plus a context canary.** Document that model traffic goes to first-party hosts by default, that adding a router or marketplace host needs a recorded human decision, and that ZDR is a contract term and not a control. Add a per-run fake credential to the agent's context and treat any use as an incident.
- **C2. Body scanning in the broker.** Option B's proxy inspects request bodies and blocks or redacts known credential formats. Rejected for now. It parses attacker-influenced content inside the one component that holds the real secret, which works against the broker-as-target mitigation above. Format matching also misses card numbers in free text and business data.

Proposed: B2, in docs first. The canary part waits for a human decision on the canary service.

### Work packages

| WP | Scope | Depends on | Acceptance evidence |
|---|---|---|---|
| E1 | Docs only: provider route policy in README and the new ADR from WP4. First-party model hosts by default. A router or marketplace host needs a named decision and a pinned upstream list. ZDR is listed as a contract term, not a control. | none, can go before WP0 | Reviewed doc diff. A reader can tell which model hosts the default sandbox reaches and how to add one. |
| E2 | Spike, no repo change: where a per-run canary credential lives so the model sees it and git never does, who receives the alert, and how a hit becomes an incident record. Compare a free Thinkst Canarytoken with a self-hosted fake key. | E1, human decision 4 | Short design note in this file. States how false alarms from the user's own tools are ruled out. |
| E3 | Design note only: a warn-level check on secrets the agent reads, for example a guardrail rule on `.env`, key files or `env` output. Warn, never block, in a first version. | E1 | Note lists the patterns, the read paths the hooks can actually see, and the known misses. |

### Risks

- The canary leaks into a commit or PR and fires on a harmless reader such as a public scanner. Mitigation: E2 keeps it outside the repository tree and labels it in receipts.
- A canary hit says a prompt leaked, not where. Dragos needed a route tracer for that. Mitigation: treat a hit as "rotate everything sent in that window", as Phala advised its users.
- Warn-level checks get ignored. Mitigation: count warnings in receipts so a review can see them.
- A written policy reads like a guarantee. Mitigation: E1 states that the policy controls routes, not what providers do after receipt.

### Rollback

E1 is a doc revert. E2 and E3 change nothing in the repository until a later accepted package.

### Pending human decisions (appendix)

4. Whether to register an external canary service account (Thinkst or similar) for E2, or use a self-hosted fake key only.
5. Whether router or marketplace model hosts are ever allowed in the harness, or first-party only.
6. Whether E3's read check should stay warn-only or become a block once false positives are known.
