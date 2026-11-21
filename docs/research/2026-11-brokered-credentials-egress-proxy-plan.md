# Proposed plan: brokered model credentials at the egress container (ADR-003 follow-up 2)

- **Status:** Proposed. Not accepted, not implemented, and not permission to change the devcontainer, the egress container, `sandbox.py` or any test.
- **Date:** 2026-11-17 (Europe/Madrid).
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
| WP1 | Design note: reverse-proxy shape (one upstream, fixed path prefix, header swap, no body rewrite), where the secret is mounted, logging without secrets. | WP0 | Reviewed design section added here. |
| WP2 | Implement the proxy in `egress` (stdlib Python, like the engine). Agent service gets the placeholder and base URL only. | WP1, maintainer acceptance | Tests: request with placeholder reaches upstream with real header; any other host or path is refused; secret absent from the agent container environment, filesystem and logs. |
| WP3 | Evidence: `credential_mode: brokered` when the agent sees only the placeholder and the egress service publishes that it brokers. Never name the credential. | WP2 | `receipt` shows `brokered`; old receipts unchanged; `sandbox.py` still understates when it cannot see proof. |
| WP4 | Docs: ADR amending follow-up 2, README and devcontainer comments. | WP3 | Docs reviewed in the same PR. |

## Risks

- The upstream echoes the credential in an error body. Mitigation: strip known credential headers from responses and log bodies only on error, redacted.
- The agent CLI changes its auth flow. Mitigation: WP0 records versions; a doctor check fails closed back to `env` with a visible warning, never silently.
- A second secret path appears (for example a GitHub token) and someone extends the proxy ad hoc. Each new origin needs its own reviewed rule.
- Brokering hides the key but not its use. A compromised agent can still spend through the proxy. Rate or budget limits are out of scope here.

## Rollback

Unset the base URL and placeholder, pass the real variable again as today. `credential_mode` returns to `env`. No data migration.

## Human decisions (17 Nov 2026)

1. WP0 may start. Option B is still Proposed. WP1 onward needs a separate yes.
2. First version is API-key only. OAuth-token users are out of scope for now. WP0 still notes what happens with an OAuth token, for the record.
3. A budget or rate limit at the proxy becomes its own follow-up, outside this plan.

## WP0 results

Checked on 17 Nov 2026. This answers the unverified base-URL item in Evidence and baseline. The plan status stays Proposed. Option B stays Proposed. WP1 still needs a separate yes.

- **CLI:** `@anthropic-ai/claude-code` 2.1.326. `claude --version` printed `2.1.326 (Claude Code)`.
- **OS:** Ubuntu 24.04.5 LTS, Linux 6.12.113+, x86_64.
- **Isolation:** the CLI and the stub ran in a network namespace with only the loopback interface up. Any other host would fail inside that namespace.
- **Stub:** stdlib `http.server` on `127.0.0.1:8765`. It logged method, path, and header names. For `x-api-key` and `Authorization` it logged only whether the value equalled the placeholder `sk-ant-placeholder-wp0` (Bearer scheme for `Authorization`). Header values stayed out of the log. `POST /v1/messages` with `stream` true got a short server-sent events reply: text `ok`, stop reason `end_turn`.

Official override and gateway notes, read on the same day:

- `ANTHROPIC_BASE_URL` overrides the API endpoint for a proxy or gateway. https://code.claude.com/docs/en/env-vars
- `ANTHROPIC_API_KEY` is sent as `X-Api-Key`. `ANTHROPIC_AUTH_TOKEN` is a gateway bearer value, sent as `Authorization: Bearer`. Same page.
- `CLAUDE_CODE_OAUTH_TOKEN` is a claude.ai token from `claude setup-token`, for scripts and CI. https://code.claude.com/docs/en/authentication
- How to point Claude Code at a gateway: https://code.claude.com/docs/en/llm-gateway-connect
- Gateway shape: inference posts to `/v1/messages?beta=true`. Forward `anthropic-version` and `anthropic-beta`. With a claude.ai login and no gateway credential, `Authorization` carries that login. https://code.claude.com/docs/en/llm-gateway-protocol

Commands, placeholder only. Install: `npm install @anthropic-ai/claude-code@2.1.326`. Binary: `node_modules/@anthropic-ai/claude-code/bin/claude.exe`. Each run was `env -i` with `PATH`, `HOME`, `USER`, `LOGNAME`, `LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `TMPDIR=/tmp`, `TERM=dumb`, plus:

```
ANTHROPIC_BASE_URL=http://127.0.0.1:8765
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL=1
DISABLE_TELEMETRY=1
DISABLE_AUTOUPDATER=1
DISABLE_UPDATES=1
```

Those variables suppress telemetry, updates, and the official marketplace install. The prompt was:

```
claude -p --output-format text --permission-mode dontAsk --no-session-persistence "Reply with the single word ok."
```

API-key run added `ANTHROPIC_API_KEY=sk-ant-placeholder-wp0`. OAuth run added `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-placeholder-wp0` and left `ANTHROPIC_API_KEY` unset. Separate empty `HOME` directories. Working directory was an empty temp dir.

**API key.** The override was honoured. The stub saw one request: `POST /v1/messages?beta=true`. Body `stream` was true. Model was `claude-opus-5-5`. The placeholder was in `x-api-key` and matched. `Authorization` was absent. The CLI printed `ok` and exited 0.

Header names, in observed order: `Accept`, `Content-Type`, `User-Agent`, `X-Claude-Code-Session-Id`, `X-Stainless-Arch`, `X-Stainless-Lang`, `X-Stainless-OS`, `X-Stainless-Package-Version`, `X-Stainless-Retry-Count`, `X-Stainless-Runtime`, `X-Stainless-Runtime-Version`, `X-Stainless-Timeout`, `anthropic-beta`, `anthropic-dangerous-direct-browser-access`, `anthropic-version`, `x-api-key`, `x-app`, `Connection`, `Host`, `Accept-Encoding`, `Content-Length`.

**OAuth token, for the record.** The override was honoured for this placeholder. The stub saw one request, same path, `stream` true. Model was `claude-sonnet-5-5`. Header names matched the API-key request, with `Authorization` in place of `x-api-key`. The scheme was Bearer and the token matched the placeholder. `x-api-key` was absent. The CLI printed `ok` and exited 0. The value was the placeholder above. A token from `claude setup-token` was not available. The first version stays API-key only.

Neither run called `/v1/models` or `/v1/messages/count_tokens`. The temp homes did not store the placeholder.

**Verdict: pass.** API-key mode sends the model request through `ANTHROPIC_BASE_URL`, and the credential is in `x-api-key`. WP1 can be proposed.
