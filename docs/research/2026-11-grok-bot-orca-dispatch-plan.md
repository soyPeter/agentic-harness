# Proposed plan: Grok Bot as chief of staff, Orca as the local worker

- **Status:** Proposed. Not accepted, not implemented, and not permission to start Orca, open a port, install a gateway, or change agent hooks.
- **Date:** 2026-11-27 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-grok-bot-orca-dispatch-plan.md`.
- **Decision authority (proposed role, unassigned):** Pedro. Merge stays human (ADR-002). Starting `harness.py orca` stays a user action until he changes that rule (ADR-013 and the self-rollout plan).
- **Related:** [ADR-002](../adr/ADR-002-change-class-ladder.md) (human PR merge), [ADR-003](../adr/ADR-003-sandbox-backends.md) (container boundary, egress outside the agent container, Orca-in-sandbox follow-up 6 still deferred), [ADR-013](../adr/ADR-013-orca-self-rollout.md) and [2026-11-orca-self-rollout-plan.md](2026-11-orca-self-rollout-plan.md) (only the user starts `harness.py orca`), KB note `ai-Morlex-Grok-Bot-Hermes-Bridge-Orca-2026-11`.

## Why this is a plan

On 27 Nov 2026 Morlex posted a Grok Bot plus Hermes setup ([post](https://x.com/0xMorlex/status/2126364069066158523), [prompt](https://x.com/0xMorlex/status/2126366617743618235)). A cloud bot plans and reports. A local agent does work that needs the owner's disk, GPU or chosen model. The link is a two-tool MCP bridge (`hermes_ask`, `hermes_status`), with a status check before the first job, a brief per job, at most three verify rounds, a daily summary, and a human OK for deletes, payments, posts and merges. The named plugin matches [iamsupersocks/grokbot-hermes-bridge](https://github.com/iamsupersocks/grokbot-hermes-bridge) (README and adapter code read at `78eda8b`). That gateway binds to localhost and expects a public HTTPS front end plus owner-code OAuth.

Pedro asked whether the same shape can use Orca instead of Hermes. The workflow split is feasible. A public copy of that gateway is not the first step, and it is not a duplicate of the self-rollout plan: ADR-013 covers how Pedro runs harness waves in Orca, not how Grok Bot should dispatch work to Orca.

## Evidence and baseline

- **Morlex setup:** post, first-reply prompt, 21-second video frames, and the bridge repo, read 2026-11-27. Practitioner write-up, not a measured study. The gateway was not run.
- **Orca on Estix (read-only, 2026-11-27):** CLI 1.4.277 at `/usr/local/bin/orca`. `orca status` reported the app running and the runtime ready. Commands that map to the two-tool shape already exist: `orca status --json`, `orca worktree ps --json`, `orca agent list` / `show` / `read`, `orca agent launch`, `orca worktree create --agent --prompt`. Official docs: [CLI overview](https://orca.dev/docs/cli/overview), [CLI reference](https://orca.dev/docs/cli/reference). `orca serve` is a headless runtime for pairing Orca clients, including a `--refuse-public` bind mode. It is not a Grok Bot MCP server. Orca can attach MCP servers to its own bots. The docs I read do not offer Orca itself as a Streamable HTTP MCP endpoint for Grok Bot.
- **Harness policy (origin/main, read 2026-11-27):** ADR-002 keeps PR merge human. ADR-003 makes the container the unattended boundary and enforces egress in a sibling container. Follow-up 6 is deferred: Orca starts workers on the host in the task worktree, so work whose class needs a container is refused on the host. The self-rollout plan (accepted defaults, 10 Nov 2026) says only the user starts `harness.py orca` and `orca-nightly`. Agent hooks refuse those commands. Agents may use `--dry-run`, `orca-digest`, `state`, `report` and `escalations`. Delivery under `HARNESS_PROFILE=triple` refuses `--merge` and `--trust`.
- **Already available without a new gateway:** this Grok Bot can run approved commands on Estix. That is a generic shell path, wider than two tools, and it already waits on Pedro's approval cards.
- **Not checked:** whether a Grok Bot desktop app on Estix can reach a localhost MCP server without a public tunnel; the exact hook code path that refuses `harness.py orca`; live behaviour of `orca agent launch` receipts; whether unattended Grok Bot runs have Estix tools enabled.

## Options

| Option | What it is | Benefit | Cost / risk |
|---|---|---|---|
| A. Do nothing | Keep today's ad-hoc Estix commands and Pedro-started `harness.py orca` waves | No new surface, no policy change | No standing brief, no mandatory status check, no shared verify loop. Easy to use a raw shell when a worktree launch would be safer |
| B. Skill and inspect-first dispatch, no new network | A Grok Bot skill that plays chief of staff: status first, one brief per job, at most three verify rounds, human OK for deletes, payments, posts and merges. Inspect with `orca status`, `worktree ps`, `agent list` / `show` / `read`, and harness `report` / `escalations`. Do not start workers until Pedro says launches are allowed, and then only through `harness.py orca --pr` (no `--merge`) for repo work | Gets the useful Morlex workflow on tools that already exist. No public port. Leaves ADR-002, ADR-003 and the start-hook rule in place | Skill discipline is only as strong as the bot following it. Launch remains blocked until Pedro changes the start rule. Generic Estix shell still exists beside the skill |
| C. Self-hosted MCP gateway, Hermes-bridge shape | A new local gateway with exactly two tools (`orca_status`, and later a tightly wrapped `orca_ask`), OAuth, localhost bind, bounded argv, no generic shell. A public HTTPS tunnel only if Pedro later asks for one | Standing tools without a one-off shell; narrower than today's Estix shell if the bot is then barred from raw `orca` commands | New internet-facing or tunnel-facing surface on Estix. `orca agent launch` is a full coding agent, not a 180-second oneshot, so a leaked token is remote control of the machine. Conflicts with "only the user starts orca" until that rule is changed. Easy to bypass the ADR-003 host-start gate if `orca_ask` wraps raw `agent launch` |

**Proposed: B.** Start with a read-only audit (WP0). Write the skill as inspect-first. Add launch only after Pedro answers the decisions below, and only through the harness entry point. Park C until B is in use and a separate security review exists. A stays the fallback.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP0 Audit (read only) | Confirm Estix tool access from this Grok Bot; record `orca status --json` and that list/show/read/ps work without starting an agent; quote the hook text that refuses `harness.py orca`; confirm no existing Grok Bot MCP or Orca-bridge in the repo or on Estix; note whether a localhost MCP (no public tunnel) is even possible for this client | none | Short findings in this file or a follow-up appendix. **Stop if the inspect path already fails, or if an equivalent skill or bridge already exists.** |
| WP1 Inspect-first skill | Draft a Grok Bot skill or pasted prompt: role, status check, brief schema (goal, worktree or folder, done-looks-like, how to check), three-round verify cap, daily summary, human OK list, "do not claim done unless `orca agent show` / harness report says so". Launch section stays "ask Pedro" until he allows WP2 | WP0 | The skill is written and reviewed. A dry run on a real inspect-only question (status, list open worktrees, report escalations) follows the brief and does not start an agent. No hook, firewall, or ADR change |
| WP2 Optional launch path | If Pedro allows it: document the only allowed start command for repo work, `harness.py orca --pr` (or the pinned thin launcher), in a dedicated checkout, with `HARNESS_PROFILE` still refusing `--merge`. Raw `orca agent launch` stays out of scope for change classes that need a container (ADR-003 follow-up 6). Keep the existing hook unless Pedro explicitly wants agents to start waves | WP1 and Pedro's yes | A written runbook plus a `--dry-run` transcript. A live start happens only if Pedro runs it, or if he has changed the hook and is present. Deliverer still does not merge. Receipt still records the sandbox |
| WP3 Parked gateway | Only after B is in use and Pedro asks: design a two-tool localhost gateway modelled on grokbot-hermes-bridge (fixed binary, no shell, OAuth, fail-closed, filtered status, bounded output). Default bind is 127.0.0.1. No public tunnel in v1. Revisit C's tunnel only as a later decision | WP2 or an explicit ask | Design note and threat list. No code until that design is accepted |

Out of scope: implementing a gateway, opening a public HTTPS tunnel, changing ADR-002 or ADR-003, auto-merge, installing Hermes, pointing the official Hermes bridge at Orca, enabling `orca serve --allow-public`, creating Linear issues, or starting a live Orca wave.

## Risks and rollback

- **Policy bypass:** a skill or gateway that calls `orca agent launch` or `harness.py orca` would break the current "only the user starts it" rule and can skip the container start gate. Mitigate by keeping WP1 inspect-only and by refusing raw launch in WP2.
- **Host execution:** Orca workers still start on the host today (ADR-003 follow-up 6). Dispatching more work from Grok Bot makes that gap more often hit, not smaller. The start gate must keep refusing container-class work on the host.
- **Public endpoint (option C):** a tunnel in front of `orca_ask` is remote execution on Estix if the owner code leaks. That is why C is parked and why v1, if ever built, stays on localhost.
- **Generic shell still exists:** the skill cannot remove Estix Shell. The runbook should say when to refuse a raw command and use the inspect tools instead.
- **Secrets in prompts and receipts:** job briefs and `agent read` output can carry repo contents. Do not paste secrets into a brief. Status output should stay filtered, as the Hermes bridge does.
- **Rollback:** WP1 is a skill or prompt; delete or disable it. WP2 is a runbook and, only if Pedro asked, a hook change that reverts with a reviewed PR. No gateway is installed in this plan, so there is no service to tear down.

## Decisions needed (human)

1. Is option B acceptable as the start, beginning with WP0 (read only)?
2. May Grok Bot start Orca workers at all? If yes, is the only allowed start `harness.py orca --pr` in a dedicated checkout, with `--merge` still refused?
3. Should the agent hooks keep refusing `harness.py orca`, so Pedro still types the live start himself after the bot prepares a dry-run?
4. Do you want a later MCP gateway (option C), and if so must it stay on localhost with no public tunnel?
