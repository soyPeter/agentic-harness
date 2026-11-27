---
name: orca-inspect
description: Read-only Orca status on Estix for Grok Bot. Use it to list running, stuck and finished agents, and to write the daily Orca report. Never launch, stop, message or create worktrees.
applies-to: Orca CLI 1.4.277 on Estix
last-verified: 2026-11-27
sources: Orca CLI 1.4.277 help; docs/research/2026-11-grok-bot-orca-dispatch-plan.md Decisions (2026-11-27); ADR-013; payload/owned/backbone/HOOKS.md (user-only orca commands)
---

# Orca inspect (WP0, read only)

Pedro manages his own Orca bots on Estix. This skill only inspects. It does not start work.

CLI: `/usr/local/bin/orca`, 1.4.277. Prefer `--json` when parsing. Do not use `--pairing-code` or `--environment` unless Pedro names a remote runtime.

## Allowlist

Run only these, with the flags below (plus `--help` and `--json`):

- `orca status`
- `orca worktree ps` (`--limit <n>`, `--since <age>` such as `24h`)
- `orca worktree list` (`--repo <selector>`, `--limit <n>`)
- `orca worktree show --worktree <selector>`
- `orca worktree current`
- `orca agent list` (`--worktree <selector>`, `--state working|blocked|waiting|done`)
- `orca agent show <id>` (location and last known state only)
- `orca agent installed` (installed CLIs, not running agents)
- `orca agent read <id>` (`--limit <n>`), only for an agent this bot started, or when Pedro asks for that session

`--agent-wait` on `worktree ps` is optional. Skip it if it would block.

For harness backlog state, these inspect commands are already allowed by the hooks. Use them from a `/tmp` worktree or the project's Orca worktree, never from `/Users/peter/Work/repos/agentic-harness` (that checkout stays untouched):

- `python3 scripts/harness/lib/harness.py orca --dry-run`
- `python3 scripts/harness/lib/harness.py orca-digest`
- `python3 scripts/harness/lib/harness.py state`
- `python3 scripts/harness/lib/harness.py report`
- `python3 scripts/harness/lib/harness.py escalations`

## Forbidden

Do not run, wrap, or ask a shell to run:

- `orca agent launch` and `orca worktree create` (including `--agent` or `--prompt`)
- `orca worktree rm`, `worktree set`, `worktree activate`
- `orca agent hooks on`, `hooks off`, `hooks prepare-codex` (`hooks status` is also out of scope)
- `orca search` (full session text)
- `orca orchestration send`, `orchestration worker-stop`, and any other `orchestration` write
- `orca terminal send`, `terminal create`, `terminal close`
- `orca account add`, `account select`, `account rm`, `orca serve`, `orca open`
- Any other `orca` subcommand that creates, changes, stops, messages, or deletes
- `python3 scripts/harness/lib/harness.py orca` without `--dry-run`, and `orca-nightly`

Agent hooks already refuse `harness.py orca` and `orca-nightly` from an agent. Dry runs stay allowed. Leave those hooks in place (ADR-013). If a job should run, write Pedro a brief and the exact `harness.py orca --pr` command, and stop. He launches it.

## Coexistence

- Future branches and worktrees for jobs this bot prepares use a `tronkdy/` prefix, for example `tronkdy/short-name`. The existing Orca bot named Tronkdy is Pedro's. Do not treat it, or its home folder, as a job this bot started.
- `orca agent list` and `orca worktree ps` may list every agent. That is allowed. Do not run `orca agent read` or `orca search` on an agent this bot did not start, unless Pedro asks for that session.
- Those list commands also print `last asked`, `last said`, and `last reply` (or `lastAssistantMessage` in JSON). That is a transcript snippet. Do not quote it in the report for agents this bot did not start. Use state, title, worktree, repo, branch, and PR only.
- `orca agent show` is location and state, not the transcript. Still skip it for Pedro's agents unless the report needs to know where one is, or he asks.
- Concurrency cap: at most one job whose branch or worktree name starts with `tronkdy/`.
- Skip a launch when Estix is under load. Under load means the 1-minute load average is at or above the number of logical CPUs (`sysctl -n hw.ncpu`, 10 on Estix as of 2026-11-27), or three or more agents are in state `working`. WP0 does not launch. Still record load and the working count in the report.

## Daily report

A routine may call this skill and ask for the daily report. The report is a short message to Pedro, in Europe/Madrid time, with:

1. Orca status: app running or not, runtime ready or not.
2. Estix load: 1/5/15 averages, CPU count, and whether it is under load.
3. Running: agents in state `working` (worktree, repo, title, kind).
4. Stuck: agents in state `blocked` or `waiting`, and worktrees whose open PR checks failed.
5. Finished: worktrees or agents that completed since the last report, or in the last 24 hours (`worktree ps --since 24h`).
6. PRs waiting on Pedro: open or draft PRs from `worktree ps` (number, title, draft or open, checks).
7. This bot's jobs: any `tronkdy/` branch or worktree. Say none if there are none.

Do not claim an agent is done unless `orca agent list` or `orca agent show` says `done`, or a harness `report` says so. Do not paste secrets. Filter status output.

## Brief for a later launch

If Pedro should start a job, give him a brief (goal, worktree or folder, what done looks like, how to check) and one command: `python3 scripts/harness/lib/harness.py orca --pr`, in a dedicated checkout. Do not include `--merge` or `--trust`. Do not run it.

## Linked skills

None.
