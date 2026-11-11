# ADR-003: Sandbox backends and sandbox evidence

## Status
Accepted

## Date
2026-11-07

## Context
`harness.py run` drives tasks unattended. For each task it starts a fresh agent session with `HARNESS_AGENT_CMD`
(a shell command, the prompt on stdin) in the folder the runner runs in. Unattended runs are meant for
`.devcontainer/harness-agent/`: the user opens the project in that container and starts `run` there, and the agent
skips its permission prompts (`--dangerously-skip-permissions`) because the container is the boundary.
`harness.py orca` hands each step to an Orca worker, which Orca starts on the host in the task's worktree.

The container today:

- It is a plain Docker container on the host's kernel, built `FROM node:22-bookworm`. That is a tag, so two builds of
  the same files can differ.
- `init-firewall.sh` limits outbound traffic to an allowlist (the Anthropic API, GitHub, `HARNESS_FIREWALL_ALLOW`)
  with iptables rules applied **inside the container it polices**. So the container gets
  `--cap-add=NET_ADMIN --cap-add=NET_RAW`, and the agent user may run the script as root through sudo, with its own
  `HARNESS_FIREWALL_ALLOW`.
- Checked on a real container (2026-11-07): the agent re-ran the script through sudo and the rules in force changed.
  This time the list emptied and cut GitHub off, because DNS is dropped while the script rebuilds it. Any way to root
  (a sudo or setuid flaw, a bug in the script) rewrites the rules at will.

The change receipt (`harness.py receipt`) states what the harness can prove about a task, but not where the work
ran. A run inside the container and a run on the host give the same receipt.

The research ([2026-11 landscape](../research/2026-11-agent-sdlc-landscape.md), recommendation 1 and Space 6g) ranks
this first: define a backend interface and the evidence before touching any vendor.

- Hosted sandbox vendors are consolidating faster than the harness ages:
  - Daytona archived its open-source repository on 2026-10-03, and its core has been private since June 2026.
  - Gitpod became Ona, which OpenAI is acquiring; Blaxel is joining Baseten and Koyeb Mistral; Morph is gone.
  - Northflank has an unresolved control-plane secret compromise.
- No sandbox vendor reviewed publishes a PCI-DSS attestation.
- The CI floor, `harness-verify`, checks every pull request with the base branch's verifier (ADR-001). It must keep
  depending on nothing but that engine and git: no vendor SDK, image or control plane.

Prior art: [sandcastle](https://github.com/mattpocock/sandcastle) (MIT) defines a sandbox provider as `create`
returning a handle with `exec`, file copy in and out, and `close`.

- Worktrees, branches and commit extraction stay with the orchestrator.
- Bind-mount providers (Docker, Podman, the OS sandboxes) share the worktree with the host; isolated ones (E2B,
  Daytona, Modal, Vercel) copy files across.
- A no-sandbox provider runs on the host.

## Decision
Where an unattended session runs becomes a **sandbox backend's** job, behind one interface in the engine. Every
receipt records the sandbox its judge pass ran in. The local devcontainer stays the default backend and is the only one
the CI floor may use. Vendor backends come later, each with its own decision.

### The interface
A backend provides six operations:

| Operation | Contract | The local `devcontainer` backend |
|---|---|---|
| `create(workspace)` | provides a sandbox for a task's workspace and returns a handle | a handle on the environment the runner is in: it already runs where its sessions run, so nothing is started |
| `exec(handle, command, stdin, log, timeout)` | runs a shell command in the sandbox's workspace, stdin in and output to the log; returns the exit code, or none once the timeout has stopped it | a subprocess in the workspace folder, as `run` started sessions before |
| `copy_in(handle, host_path, sandbox_path)`, `copy_out(handle, sandbox_path, host_path)` | moves a file across the boundary | a plain copy: the workspace is a bind mount, so the sandbox sees the host's files |
| `egress_policy()` | the allowlisted host names in force, or none when nothing restricts outbound traffic | the list the egress container publishes (below), else none |
| `teardown(handle)` | destroys the sandbox; runs after every session, a timed-out one included | nothing: the container is the user's and outlives the run |
| `identity()` | the sandbox evidence (below) | read from the environment |

- A backend runs sessions; it doesn't own git. Worktrees, branches, commits, pushes and pull requests stay with the
  runner, as in sandcastle.
- `HARNESS_SANDBOX_BACKEND` (user-only, default `devcontainer`) chooses the backend. v1 has only `devcontainer`. Any
  other value is a doctor error, so `run` and `orca` refuse to start: an unknown backend fails closed.
- The interface lives in the engine (`scripts/harness/lib/sandbox.py`), standard library only. An adapter talks to a
  vendor through its CLI (a subprocess) or its REST API (`urllib`), never by importing an SDK. The vendor SDKs need
  Python 3.10 or 3.11; the engine runs on 3.8.
- v1's runner calls `create`, `exec` and `teardown` for each session; the judge-stop hook calls `identity`, which reads
  `egress_policy`. `copy_in` and `copy_out` are needed once a backend doesn't share the host's files, so nothing calls
  them yet.

### The local devcontainer: the default, and the only backend the CI floor may use
- `devcontainer` runs each session where the runner runs, as `run` did before this ADR. That is inside the
  harness-agent container when the user started `run` there, and on the host otherwise. It starts and destroys
  nothing.
- The CI floor never selects a backend. `verify`, which `harness-verify` runs, doesn't read `HARNESS_SANDBOX_BACKEND`,
  selects no backend and starts no agent session. A backend added later is for `run`; `harness-verify` keeps needing
  only the base branch's engine and git.
- `orca`: Orca starts the workers itself, on the host in each task's worktree, and v1 keeps that. The backend check
  applies (an unknown backend stops `orca`), and an orca task's evidence is recorded at its judge pass, like any
  other task's. Running Orca's workers inside a backend's sandbox is a follow-up.

### Sandbox evidence
| Field | Meaning | Inside the harness-agent container | Anywhere else |
|---|---|---|---|
| `backend` | the backend that ran the session | `devcontainer` | `devcontainer` |
| `isolation_class` | the boundary between the agent and the host: `none` < `container` < `userspace-kernel` (gVisor) < `microVM` (Firecracker, Cloud Hypervisor, Kata) < `dedicated-VM` | `container`, once the process shows the container's restrictions (below) | `none` |
| `base_image_digest` | the digest of the base image the Dockerfile builds from; `unpinned` when that base is named by a tag. It does not cover the packages or the agent CLI installed on top | the base's digest, as baked into the image's environment | `none` |
| `allowlist_hash` | `sha256:` over the allowlisted host names, lower-cased, deduplicated, sorted, one per line | of `/run/harness-egress/allowlist`, the list the egress container publishes | `none` |
| `region` | where the sandbox runs: a hosted backend's region or jurisdiction | `local` | `local` |
| `control_plane` | who creates and holds the sandbox | `local` (the machine's container engine) | `none` |
| `credential_mode` | how the agent's credentials reach it: `host`, `env`, `login`, later `brokered` | `env` with `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` set, else `login` (the login stored in the container) | `host` |

- **Where it is recorded.** The judge-stop hook records the evidence with every judge verdict, as `sandbox` in
  `backbone/.verdicts/<task>.judge.json`. It is taken from the environment the hook runs in, which is where the judge's
  evidence was produced, the harness's own test run included. It is committed with the verdicts, so CI, reviewers and
  other clones see it. Recording it when the receipt is printed instead would describe the machine printing it.
- **Where it is shown.** `receipt` shows the evidence of the judge pass it relies on: a SANDBOX section in the text and
  `sandbox` in `--json`. A judge pass recorded before this ADR shows `null` (text: "not recorded"). The pull requests
  `run --worktree --pr` and `orca` open carry it inside the receipt, and so does `linear receipt`.
- **The local backend vouches only for what it can see.** `HARNESS_SANDBOX_IMAGE` is baked into the harness-agent
  image, but a host can export it, and `docker run --cap-add NET_ADMIN` or `--privileged` gives a container the same
  variable. So the backend reports `container` only when the process itself shows the container's restrictions: Linux,
  a container marker (`/.dockerenv` or `/run/.containerenv`), `NoNewPrivs` set in `/proc/self/status`, no NET_ADMIN,
  NET_RAW or SYS_ADMIN in its effective or its bounding set (`CapEff` and `CapBnd`: a non-root process's effective set
  is empty even when `--cap-add` gave it a capability, so the bounding set is what shows it), and the egress
  container's allowlist readable at `/run/harness-egress/allowlist` with `HARNESS_EGRESS_ALLOWLIST` naming that path.
  Anything else reports `none`, with `isolation_reason` saying which check failed, other containers included. It
  understates rather than overstates. These are checks on what the process shows, not proof of how the container was
  started: a container with the same restrictions and the same published list passes them.
- The evidence also carries `isolation_reason`, beside the fields above: why the class is what it is.
- `allowlist_hash` identifies the policy as published, not the addresses the names resolved to, and not the GitHub
  address ranges `init-firewall.sh` adds from `api.github.com/meta`, which change. Anyone can recompute it from the
  list. A receipt says so.
- A container with no published allowlist is flagged in the receipt ("container without an allowlist"): its outbound
  traffic isn't limited by the egress container, whatever its class.
- The evidence names how credentials arrive, never a credential.
- It is a record, not a gate: v1 refuses nothing because of it.

### The image is pinned by digest
- The Dockerfile names its base once, `ARG HARNESS_SANDBOX_IMAGE=node:22-bookworm@sha256:7702d8aa…` (the multi-arch
  index of 2026-11-05), builds `FROM ${HARNESS_SANDBOX_IMAGE}`, and bakes the same value into the image's environment.
  The evidence names the base the image was really built from: a build-arg override shows up as given, and one
  without a digest is `unpinned`.
- The digest covers the base. The packages and the agent CLI the Dockerfile installs on top aren't pinned by it. The
  evidence field is `base_image_digest`; a receipt recorded before the rename says `image_digest`, which it reads as the
  same thing.
- Moving the base is a reviewed change to one line.

### Egress is enforced outside the agent's container
`devcontainer.json` names a Compose file with two services, both built from the same image:

- `egress` runs as root with NET_ADMIN and NET_RAW.
  - It runs `init-firewall.sh` in the network namespace it owns, with the same allowlist as before. Outbound IPv6,
    which nothing allowed, is now dropped instead of left open.
  - It writes the host list to a volume, then waits.
  - Its health check passes once the OUTPUT policy is DROP and the list is written.
- `agent` joins that namespace (`network_mode: service:egress`), so its traffic meets the same rules.
  - It drops NET_ADMIN and NET_RAW, runs with `no-new-privileges`, and has no sudo.
  - It mounts the published list read-only at `/run/harness-egress/allowlist`, the one path the evidence reads
    (`HARNESS_EGRESS_ALLOWLIST` names it).
  - It starts only once `egress` is healthy.

The agent can't reach the rules: it has no capability to change them and no sudo, and the egress container's
processes and files are in namespaces it doesn't share. If `egress` stops, the shared namespace loses its network
interface and the agent loses its network, so it fails closed. `HARNESS_FIREWALL_ALLOW` moves from `devcontainer.json`
to the `egress` service in the Compose file.

An installed sandbox from before the Compose file has the single-container shape, and that shape must not pass
silently:

- Inside the harness-agent image (`HARNESS_SANDBOX_IMAGE` set), an egress allowlist that isn't published at
  `/run/harness-egress/allowlist` is a doctor error, so `run` and `orca` refuse to start.
- `doctor` warns when `devcontainer.json` names no `dockerComposeFile`, or can't be parsed (it is read as JSONC).
  `update` warns when it keeps a locally edited `devcontainer.json` that conflicts with the new one, and says what to
  merge from the `.harness-new` file.

Still open after v1:

- DNS (port 53) is allowed to any resolver, so data can leave in DNS queries.
- Names resolve once, at start.
- TLS isn't inspected, and the allowlist is per host, not per path.
- The agent's API credential is in its environment.
- The container shares the host's kernel.

### Vendor backends: later candidates, not v1
| Candidate | Why it is a candidate | Risks the research found |
|---|---|---|
| **E2B** | Apache-2.0 Firecracker stack; BYOC in your VPC or Embed on one node; control-plane egress with a fail-closed proxy; secrets resolved at egress; memory fork for `orca` fan-out | Enterprise and BYOC are quote-only with a one-year commitment; BYOC still sends aggregate metrics to E2B; private cloud isn't GA; fast SDK churn (Python 3.11 or later), so CLI or REST only; SOC 2 Type II but no PCI-DSS attestation |
| **Freestyle** | control-plane firewall, allow-only, with the action required rather than defaulted; hibernate with memory; branching | pricing, company and licence unverified; its docs carry instructions addressed to evaluating agents; no PCI-DSS attestation found |
| **Coder** | fully self-hosted control plane; Terraform workspaces; reuses `devcontainer.json`; Agent Firewall audit log | AGPL core with the enterprise features behind a licence key; real ops burden; Docker-in-Docker weakens the boundary; its nsjail mode needs `CAP_NET_ADMIN` and landjail has a documented bypass; full-internet egress by default; no PCI-DSS attestation found |
| Daytona | not a candidate to self-host | open-source repository archived 2026-10-03, core private since June 2026, the frozen AGPL v0.190.0 unpatched; its control plane stays SaaS even with BYOC; its egress proxy terminates TLS with a vendor CA. At most a SaaS opt-in for non-regulated profiles |

- None of them publishes a PCI-DSS attestation. For regulated work the control stays keeping cardholder data out of
  the sandbox (allowlist, scoped credentials, human merge) and making that exclusion auditable, which this evidence
  starts.
- Each adapter gets its own ADR and must pass the research's egress parity checks before it can be selected:
  - outbound to a host off the list fails on every protocol;
  - DNS doesn't leak to an unlisted resolver;
  - TLS to a listed host works;
  - no host credential is in the guest;
  - nothing but the workspace is mounted;
  - teardown is guaranteed after a budget, a timeout or a stall.
- A backend with snapshots or forks must keep the egress policy with them, or re-assert it on resume and fail closed
  if it can't.

### v1 (this change)
1. `sandbox.py` with the interface and the `devcontainer` backend, and `HARNESS_SANDBOX_BACKEND` with its doctor check.
2. `run` starts its sessions through the backend, with no change in behaviour.
3. The judge-stop hook records the evidence; `receipt` shows it in text and `--json`.
4. The image's base pinned by digest, and the reference baked into the image.
5. The egress allowlist enforced from a separate container; the agent's container without NET_ADMIN or NET_RAW.
6. `tests/test-sandbox-evidence.py` in the self-test, and `tests/test-sandbox-egress.py` against a real container
   (with `HARNESS_E2E=1`).
7. Not in CI yet. A Linux job for `tests/test-sandbox-egress.py` with `HARNESS_E2E=1` would be the only job that runs
   the container path, and the test skips without docker or the devcontainer CLI, so a job would need guard steps. It
   isn't added because the test doesn't build reliably here. On Docker Desktop 29.8.2 (buildx v0.37.2), devcontainer CLI
   0.88.0 passed all 11 tests in one full run; the next full run stopped the `Tamper` class, and `Tamper` alone failed
   in two of two runs. 0.90.0 stopped the `Allowlist` and `Tamper` classes. Each failure is buildx's "additional
   privileges requested: pass --allow=fs.read=…" error for the Dockerfile the CLI writes under the temp folder. That is
   buildx's check for files a bake reads outside its context, so it isn't switched off here:
   `BUILDX_BAKE_ENTITLEMENTS_FS=0` made the failing class pass, but the buildx material found disagrees on what it does.
   To settle it, run the test in a Linux job with the same CLI and buildx, and add the job, with its guard steps, once
   it passes there.

## Alternatives considered
- **A vendor adapter first (E2B or Daytona):** gives microVM isolation soon, but without the local fallback and the
  evidence, each vendor's exit or breach becomes the harness's problem, and the CI floor risks depending on one.
- **Keep the container as it is and record nothing:** no work, but a receipt can't tell a sandboxed run from a host
  run, and the firewall stays inside the container it polices.
- **An HTTP(S) proxy as the egress point** (the agent on an internal network, `HTTPS_PROXY` set): it would close DNS
  and log every host. But it only works for tools that honour the proxy variables. Java's tools (Gradle, Maven) and
  Node's built-in `fetch` don't, so builds would break. The two-container design keeps today's transparent rules.
- **eBPF egress enforced from the host** (as Containarium does): audit-logged denials and no capability in the guest at
  all. But it needs a privileged agent on a Linux host kernel, which Docker Desktop and OrbStack on macOS don't give
  the developer.
- **Record the evidence when the receipt is printed:** simpler, but a receipt printed on the host for a task run in the
  container would describe the host.
- **Record it in the event log (`.git/harness/events.jsonl`):** that log isn't committed, so CI and other clones would
  never see it.
- **Treat any container as `container`** (`/.dockerenv`): it would vouch for containers whose egress and credentials
  the harness knows nothing about.

## Consequences
- **Easier**:
  - A receipt says where its judge pass ran, and a run that wasn't isolated shows it (`isolation_class: none`).
  - A vendor backend plugs in behind one interface without touching the runner's git handling, and the default
    and the CI floor don't depend on it.
  - A root escalation inside the agent's container no longer opens its network: the capability isn't in the container
    at all.
  - Two builds of the sandbox start from the same base.
- **Harder**:
  - The sandbox is two containers and a Compose file. A project that edited `devcontainer.json`, for example to set
    `HARNESS_FIREWALL_ALLOW`, gets the new version as `devcontainer.json.harness-new` and moves its edits into the
    Compose file. Until it does, `doctor` warns, and inside the image `run` and `orca` refuse to start.
  - An image built before this ADR has no `HARNESS_SANDBOX_IMAGE`, so its judge passes record `isolation_class: none`
    until it is rebuilt. A sandbox whose agent still holds NET_ADMIN, or runs without `no-new-privileges`, records
    `none` too, with the reason.
  - Moving the base means updating the digest by hand.
- **Unchanged**:
  - `run` starts sessions where it runs, with the same command, budgets, retries and logs.
  - `orca` starts its workers through Orca.
  - `verify` and `harness-verify` don't involve any backend.
  - Thin installs still come without the sandbox, so their judge passes record `none`.
- **Follow-up work**, each as its own change:
  1. DNS: resolve only allowlisted names from the egress container, and drop port 53 everywhere else.
  2. Credentials brokered at egress, so the agent's API key stays outside its container (`credential_mode: brokered`).
  3. Pin the whole built image (publish it and pin its digest), not just its base.
  4. Gate on the evidence: for example `schema`-class work needs at least `container`, checked from the recorded
     evidence (ADR-002's ladder).
  5. `run` on the host starting the sandbox itself, instead of the user starting `run` inside it.
  6. Orca's workers inside a backend's sandbox.
  7. A first isolated backend, behind its own ADR, passing the egress parity checks.
  8. Egress denials logged and cited by the receipt.
  9. The sandbox for thin installs.

## Follow-up status
- **4. Gate on the evidence: done (2026-11-11).** `HARNESS_SANDBOX_REQUIRE` (user-only, default `schema=container`)
  names the isolation class each Change-Class needs, as `<class>=<isolation class>` pairs. A pair holds for its class
  and every class above it on ADR-002's ladder. A task of such a class starts only in a session whose own sandbox has
  that class (`start`, an edit of `3-TASKS.md`), and finishes only when its latest judge pass recorded one (`finish`, an
  edit, and `verify`, so the pre-commit hook and CI check the recorded evidence, never their own sandbox). It fails
  closed: a judge pass recorded before the evidence, an unknown isolation class or backend, and a setting that can't be
  read all refuse, and the last is a doctor error. `run` skips such a task before starting a session for it, and the
  receipt says what the class requires and whether the judge pass met it. The evidence stays a record of the sandbox;
  the gate is what refuses.
- **9. The sandbox for thin installs: done (2026-11-11).** `init --thin`, `pin` and `update.sh --to-thin` install
  `.devcontainer/harness-agent/` from the pinned release; `pin` and `--to-thin` update the files nobody edited and keep
  an edited one with the release's copy beside it (`<file>.harness-new`), by the hashes the lock records under `kept`,
  as `update.sh` does. When the container starts, `thin-engine.py` fetches the pinned release into the launcher's engine
  cache, refuses it unless it is the pinned commit with no local changes, and links it into the folder
  `CLAUDE_CODE_PLUGIN_DIRS` names, so every Claude Code session in the sandbox loads the pinned plugin and its hooks,
  and judge passes record the same evidence as a full install's. Inside the image, `doctor` reports an error, so `run`
  and `orca` refuse to start, unless the sessions would load exactly the pinned plugin. Codex and OpenCode sessions in
  a thin project's sandbox get no plugin from this; the image runs Claude Code.
