# Proposed plan: review carried-over instructions on every agent model change

- **Status:** Proposed. Not accepted, not implemented, and not permission to edit any agent, skill, hook or rule.
- **Date:** 2026-11-10 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-model-change-instruction-review-plan.md`. This is an implementation plan, not an ADR. It adds a review step and a lint report. It does not change an architectural boundary.
- **Decision authority (proposed role, unassigned):** repository maintainer. Merge stays with the user as today.
- **Related:** `payload/owned/AGENTS.md`; `payload/owned/.claude/agents/*.md` and `.opencode/agents/*.md`; `payload/owned/.claude/skills/*`; `payload/owned/backbone/HOOKS.md`; [ADR-002](../adr/ADR-002-change-class-ladder.md); KB note `60-AI/Research/ai-Instruction-Carryover-Fable-5-2-Prompting-2026-11.md`.


## Decisions (2026-11-10)

Pedro accepted the following defaults:

- Option C: a model-change review checklist plus a read-only lint report, applied only when a model changes and backed by a before/after eval.
- An Orca worker runs the WP1 baseline on fixture tasks (`tests/coefficiency`, `tests/colsum`).
- The WP3 lint covers `payload/owned` only. It does not cover `catalog/`.

## Evidence and baseline

- **Source (primary, vendor):** Anthropic, [Prompting Claude Fable 5.2](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-2), read 2026-11-10. Sections "Keep caution from piling up", "Review instructions written for earlier models", "Approvals" and "Say who owns the code". The numbers below are Anthropic's own tests on their tasks. They are not independent and may not transfer to this harness.
  - One old "never retry" note cut retries after a busy tool from nearly all tries to about four in ten.
  - A general "act more freely" line changed nothing. Listing retries as a no-approval step raised retries from almost none to about half.
  - A rule that carried its own exception let an approved step run in about nine tries in ten. A separate exception line barely helped.
  - Approval rules apply exactly as written. A broad "messages outside this conversation" rule held back about half of routine requests.
  - Prompt token budgets, "think less" lines, standing delegation pushes and strict style limits can raise cost or stop working on the newer model.
- **Documented harness state (files read, behavior not audited):** at HEAD `2abcf53ad7a7b0ce418e43730751948b2863d5b4`, `payload/owned` has about 72 "Never/NEVER" lines across AGENTS.md, backbone docs, nine role files per CLI and the skills. The role files are duplicated for Claude Code and OpenCode. I found no document that says what to review when the underlying model changes.
- **Not checked:** which models the roles run on today, whether any role shows over-caution or early stops, how often roles ask for approvals they don't need, and the token cost per task. All of these are **hypotheses** until WP1 measures them.

## Problem

The harness relies on roles following written rules exactly. That is good for the merge gate. But a newer model can read the same rules more literally. Unscoped "never" rules can then block safe retries or routine steps. Old lines can also add cost. Today a model switch has no defined review, so this drift would only show up as slower or stuck tasks.

## Options

| Option | Benefit | Cost / risk |
|---|---|---|
| A. Do nothing | No work | Drift on model change goes unseen until tasks stall or cost rises |
| B. Rewrite all rules now for the latest model | Fast cleanup | Edits safety rules without evidence; risks weakening the gate; ties text to one vendor |
| C. Model-change review checklist plus a read-only lint report, applied only when a model changes and backed by a before/after eval | Evidence first; keeps every safety rule unless a person decides; vendor-neutral | Needs a small eval set; adds one step to model changes |

**Proposed: C.** A stays the fallback if WP1 shows no measurable drift.

## Work packages

| WP | Scope | Depends on | Acceptance / evidence |
|---|---|---|---|
| WP1 Baseline | Pick 5 to 10 recorded or fixture tasks across Change-Classes. Record per role: early stops, unneeded approval asks, retries after a transient tool error, tokens. Run on the current model only. | none | A short results table checked into `docs/research`. No code change. |
| WP2 Checklist | Add a "Model change review" section to an existing backbone doc. Items: absolute rules state scope and reason; a short list of steps that need no approval sits next to approval rules; no prompt token budgets; no "answer without thinking" lines; delegation lines reviewed; no ownership sentence for client or regulated code. | WP1 | Maintainer review. Text only. Gate rules unchanged. |
| WP3 Lint report | A read-only script (stdlib Python, same style as existing tools) that lists "never/always" lines without a stated reason and flags duplicate role text that has drifted between `.claude` and `.opencode`. Report only. No auto-fix and no gate. | WP2 | Unit test on fixtures with known findings. Zero changes to payload files. |
| WP4 Before/after on a model change | When a model change is next proposed, run WP1's set on old and new models. A person decides each rule edit. | WP1 to WP3, a real model change | Results table plus the human decision per edited rule. Merge by the user. |

## Guardrails

- Never weaken human merge, spec approval, the judge gate, risk escalation or secrets rules through this plan. Those rules stay as they are unless a person decides otherwise in a normal PR.
- The lint report informs. It never blocks, edits or activates anything.
- Vendor numbers are context only. Decisions use WP1 and WP4 results.

## Risks and rollback

- **Risk:** the eval set is too small to show a difference. Mitigation: report "no signal" honestly and stop at WP2.
- **Risk:** a scoped rewrite loosens a safety rule by accident. Mitigation: each rule edit is its own reviewed change with its reason.
- **Rollback:** WP2 and WP3 are docs and a standalone script. Revert the commits. No runtime or hook behavior changes.

## Decisions needed (human)

Resolved on 2026-11-10. See [Decisions (2026-11-10)](#decisions-2026-11-10).
