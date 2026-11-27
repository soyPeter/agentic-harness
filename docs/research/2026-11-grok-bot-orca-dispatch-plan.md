# Plan: Grok Bot as chief of staff, Orca as the local worker

- **Status:** Accepted for WP0 (inspect-only), 27 November 2026. Launch (WP2) stays closed. Option C stays deferred. Not permission to start Orca workers, open a port, install a gateway, or change agent hooks.
- **Date:** 2026-11-27 (Europe/Madrid). Decisions recorded the same day.
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-grok-bot-orca-dispatch-plan.md`.
- **Decision authority:** Pedro. Merge stays human (ADR-002). Starting `harness.py orca` stays a user action (ADR-013 and the self-rollout plan).
- **Related:** [ADR-002](../adr/ADR-002-change-class-ladder.md) (human PR merge), [ADR-003](../adr/ADR-003-sandbox-backends.md) (container boundary, egress outside the agent container, Orca-in-sandbox follow-up 6 still deferred), [ADR-013](../adr/ADR-013-orca-self-rollout.md) and [2026-11-orca-self-rollout-plan.md](2026-11-orca-self-rollout-plan.md) (only the user starts `harness.py orca`), skill `.claude/skills/orca-inspect/SKILL.md`, KB note `ai-Morlex-Grok-Bot-Hermes-Bridge-Orca-2026-11`.

## Decisions (2026-11-27)

Pedro accepted option B, starting with WP0, on 27 November 2026 (Europe/Madrid). He already runs his own bots in Orca, so these are the starting rules:

1. **Start option B with WP0, read only.** The bot may run `orca status`, `orca worktree ps`, `orca agent list`, and `orca agent show` / `read`, and it sends Pedro a short daily report: what is running, what is stuck, what finished, and which PRs are waiting on him. The inspect skill is `.claude/skills/orca-inspect/SKILL.md`.
2. **Inspect only for now.** Launching can be reconsidered after one to two weeks of clean WP0, and only through `harness.py orca --pr`, never raw `orca agent launch`.
3. **The hooks keep blocking agents from `harness.py orca` (ADR-013).** The bot sends Pedro a ready-made brief and command, and he launches it.
4. **The MCP gateway (option C) is deferred.** If it is ever built, it stays on localhost with no public tunnel.
5. **Coexistence guardrails**, because Pedro runs his own Orca bots:
   - Any future branch or worktree this bot prepares uses a `tronkdy/` prefix.
   - The bot never reads, messages, or stops an agent it did not start, unless Pedro asks. A read-only listing of all agents is fine. `orca agent read` of his agents' transcripts is not, unless he asks.
   - Concurrency cap: one job of this bot at a time.
   - Skip a launch when Estix is under load.

`orca agent list` and `orca worktree ps` print a short `last asked` / `last said` / `last reply` for open agents. That is a transcript snippet, not a full `agent read`. The skill still forbids quoting those snippets from agents the bot did not start. This does not conflict with the allowlist, ADR-013, or the hooks. The skill only tightens what the daily report may quote.

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

**Chosen: B**, accepted 27 November 2026, starting with WP0 (see Decisions). Write the skill as inspect-first. Add launch only after a later yes, and only through the harness entry point. Park C until B is in use and a separate security review exists. A stays the fallback.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP0 Audit and inspect skill (read only) | Confirm Estix tool access; record that `status`, `worktree ps`, and `agent list` / `show` / `read` work without starting an agent; quote the hook text that refuses `harness.py orca`; write the inspect-only skill and the daily report format. The skill is the inspect part that was listed as WP1 below | none | Findings in [WP0 results (2026-11-27)](#wp0-results-2026-11-27). Skill at `.claude/skills/orca-inspect/SKILL.md`. **Stop if the inspect path already fails, or if an equivalent skill or bridge already exists.** |
| WP1 Inspect-first skill | Covered by WP0 for the inspect path, the allowlist, coexistence rules, and the daily report. A later dry run on a live inspect-only question can still extend this package if gaps show up. The three-round verify loop waits until launches are allowed | WP0 | The skill is written. No hook, firewall, or ADR change |
| WP2 Optional launch path | Closed until Pedro says otherwise, after one to two weeks of clean WP0. If he allows it: the only start command for repo work is `harness.py orca --pr` (or the pinned thin launcher), in a dedicated checkout, with `HARNESS_PROFILE` still refusing `--merge`. Raw `orca agent launch` stays out of scope for change classes that need a container (ADR-003 follow-up 6). Keep the existing hook. The bot still only prepares the brief and command | WP0 and a later yes | A written runbook plus a `--dry-run` transcript. A live start happens only if Pedro runs it, or if he has changed the hook and is present. Deliverer still does not merge. Receipt still records the sandbox |
| WP3 Parked gateway | Deferred with option C. Only after B is in use and Pedro asks: design a two-tool localhost gateway modelled on grokbot-hermes-bridge (fixed binary, no shell, OAuth, fail-closed, filtered status, bounded output). Default bind is 127.0.0.1. No public tunnel in v1 | WP2 or an explicit ask | Design note and threat list. No code until that design is accepted |

Out of scope: implementing a gateway, opening a public HTTPS tunnel, changing ADR-002 or ADR-003, auto-merge, installing Hermes, pointing the official Hermes bridge at Orca, enabling `orca serve --allow-public`, creating Linear issues, or starting a live Orca wave.

## Risks and rollback

- **Policy bypass:** a skill or gateway that calls `orca agent launch` or `harness.py orca` would break the current "only the user starts it" rule and can skip the container start gate. Mitigate by keeping WP0 inspect-only and by refusing raw launch in WP2.
- **Host execution:** Orca workers still start on the host today (ADR-003 follow-up 6). Dispatching more work from Grok Bot makes that gap more often hit, not smaller. The start gate must keep refusing container-class work on the host.
- **Public endpoint (option C):** a tunnel in front of `orca_ask` is remote execution on Estix if the owner code leaks. That is why C is parked and why v1, if ever built, stays on localhost.
- **Generic shell still exists:** the skill cannot remove Estix Shell. The runbook should say when to refuse a raw command and use the inspect tools instead.
- **Secrets in prompts and receipts:** job briefs and `agent read` output can carry repo contents. Do not paste secrets into a brief. Status output should stay filtered, as the Hermes bridge does.
- **Rollback:** WP0 is a skill; delete or disable `.claude/skills/orca-inspect/` and its row in `backbone/9-AGENT-SKILLS.md`. WP2 is a runbook and, only if Pedro asked, a hook change that reverts with a reviewed PR. No gateway is installed in this plan, so there is no service to tear down.

## Decisions needed (human)

Resolved on 2026-11-27. See [Decisions (2026-11-27)](#decisions-2026-11-27).

## WP0 results (2026-11-27)

Read-only check on Estix, Orca CLI 1.4.277 at `/usr/local/bin/orca`. No agent was started, stopped, or messaged. `orca agent read` was not run on any live session.

- **Inspect path works.** `orca status` and `orca status --json` reported the app running and the runtime ready. `orca agent list` and `orca worktree ps` returned live rows (`--json` too). Help was checked for `agent show`, `agent read`, `worktree list` / `show` / `current`, and `agent installed`. Those extra list/show commands are read only and are in the skill as helpers around the approved set.
- **Hook text (unchanged).** `payload/owned/backbone/HOOKS.md`, under Out-of-band changes, says `run`, `orca`, `orca-nightly` and the other user-only commands "are refused to agents however the engine is started", and "Their dry runs (`orca`, `orca-nightly`, `linear`) stay allowed." [ADR-013](../adr/ADR-013-orca-self-rollout.md) says "Pedro starts real Orca runs and merges task PRs. An agent may inspect state and dry runs." WP0 does not conflict with that. The hooks were not changed.
- **No equivalent skill or bridge.** There was no `orca-inspect` skill in the repo. The existing `orca/skills/agentic-harness/SKILL.md` is for coordinators driving a harness repo inside Orca, and it already tells agents not to start `harness.py orca`. No grokbot-hermes-bridge or Orca MCP gateway was found in this repo or under the shallow Estix paths that were checked. Whether a Grok Bot desktop app on Estix can reach a localhost MCP server was still not checked; option C is deferred.
- **Transcript snippets on list commands.** `orca worktree ps` prints `last asked` and `last said` for open agents. `orca agent list` prints `last reply` (`lastAssistantMessage` in JSON). That is a snippet, not a full transcript (`orca agent read` or `orca search`). The daily report lists every agent but does not quote those snippets from agents the bot did not start.
- **Existing Tronkdy bot.** Orca already has a bot named Tronkdy, with a home folder under `~/.orca/bots/tronkdy`. The `tronkdy/` prefix is for branches and worktrees of jobs this Grok Bot later prepares. That bot is Pedro's. The skill must not treat it as a job the bot started.
- **Load and concurrency.** Estix has 10 logical CPUs. A 1-minute load average at or above that, or three or more agents in state `working`, counts as under load. The skill records this in the report and would skip a later launch. WP0 does not launch.
- **Skill.** `.claude/skills/orca-inspect/SKILL.md`, listed in `backbone/9-AGENT-SKILLS.md`.
