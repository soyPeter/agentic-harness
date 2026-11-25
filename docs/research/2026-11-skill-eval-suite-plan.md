# Proposed plan: a first eval suite for owned harness skills

- **Status:** Proposed. Not accepted, not implemented, and not permission to change skills, CI, hooks, `SKILLS.md` or any test.
- **Date:** 2026-11-25 (Europe/Madrid).
- **Target repository:** https://github.com/soyPeter/agentic-harness
- **Location:** `docs/research/2026-11-skill-eval-suite-plan.md`. If accepted, the decision goes in a new ADR. No existing ADR is changed.
- **Decision authority (proposed role, unassigned):** repository maintainer. PR merge stays with the user as today.
- **Related:** `payload/owned/backbone/SKILLS.md`; [ADR-007](../adr/ADR-007-evidence-closed-loop.md); `tests/test-eval-replay.py` (hook-gate replay under ADR-002, not skill quality). The 25 Nov sandbox-weakness plan is a separate Proposed document and is not in `main` yet.

## Why now

The harness already treats skills as a first-class gate: a routed edit requires the agent to load the skill, `SKILL.md` has a 200-line cap, and a wrong skill is recorded as a bug in `6-MEMORY.md`. What it does not do is check whether a change to a skill still produces the right steps.

Uber's 23 Nov 2026 engineering blog (https://www.uber.com/us/en/blog/optimizing-ubers-agent-skills/, read in full on 2026-11-25) describes how they eval skills at a much larger scale. Their guidance is about 5% golden cases with a fixed input and expected output, 80% real prompts graded on trajectory (the right skills and tools in the right order), and 15% author-judged cases. They run those evals in a clean remote environment, not only on the author's machine. They also say that, in their experience, a 70-90% pass rate can be more useful than 100%, because answers and judges vary.

We do not need Skill Workshop, a three-tier marketplace, or twelve usage measures. A first, small suite on two owned skills would tell us whether a skill change broke a known case before we take on LLM judges, ablation or cost telemetry.

KB note: `60-AI/Research/ai-Uber-Skill-Marketplace-Evals-2026-11.md` in the knowledge base (branch `soyPeter/uber-skill-evals-note-2026-11-25`).

## Evidence and baseline

- **Documented capability (read, not executed):** `payload/owned/backbone/SKILLS.md` on `origin/main` (commit 31a5f7c) defines frontmatter, a 200-line cap because routed skills are read in full before every routed edit, linked skills, the routing gate, and maintenance via `last-verified` and `6-MEMORY.md`.
- **`tests/test-eval-replay.py` on `origin/main`:** this is hook-gate replay for ADR-002 (inputs the gates refused or allowed). It is not an eval of skill quality or trajectory.
- **Working-tree scan, not a baseline:** on the dirty `release/0.31.0` checkout (other people's uncommitted work, left untouched), 10 owned skills under `payload/owned/.claude/skills/` were all under 200 lines, and most had no error-recovery section. WP0 must repeat the inventory on `origin/main`.
- **Not found on `origin/main`:** a CI job or test that grades whether a skill change still follows the required steps, or a linter for numbered steps and an error-recovery table.
- **Out of scope here, already covered elsewhere:** a general agent "papercut" report channel overlaps the 25 Nov sandbox-weakness plan. A harness-wide Code Mode change needs a measurement of current MCP tool-definition tokens first. An `aifx`-style wrapper is already recommended in the October Uber infra note (Platform research hub).

## Options

- **A. Status quo.** Keep the format rules and the load-before-edit gate. Skill quality stays a human fix recorded in `6-MEMORY.md`. Zero cost; a skill change can land with no case that would have caught a broken step.
- **B. Lint the existing format rules in CI, plus a small deterministic eval suite for two owned skills.** Golden cases use a fixed input and expected checks (exit code, files, required skill loaded, required commands). Trajectory cases in this first version only check the required skill and tools, not the wording of the answer. No LLM-as-judge.
- **C. B plus LLM-as-judge on real prompts (Uber's 80% band).** Rejected for now: Uber says this works best with a human-annotated set, and it adds cost and flake. Revisit once B has a stable baseline.

Proposed: B, after WP0.

## Work packages

| WP | Scope | Depends on | Acceptance evidence |
|---|---|---|---|
| WP0 | Read-only inventory on `origin/main`: owned and catalog `SKILL.md` files against `SKILLS.md` (frontmatter, line count, `last-verified`, error-recovery section). Confirm no skill-quality eval already exists. | none | Short note in this file: files read, commit, counts. Stop if a suite already exists. |
| WP1 | CI lint for rules `SKILLS.md` already requires: frontmatter keys, `name` matches the folder, body at or under 200 lines. Warn-only checks for numbered steps and an error-recovery table, unless decision 3 chooses fail. | WP0, maintainer acceptance | Lint runs in CI; existing skills are listed with their results; required-rule failures block, warn-only checks do not, unless decision 3 says otherwise. |
| WP2 | A small golden and trajectory set for two owned skills (proposed: `change-review` and `security`, or the two Pedro names). Deterministic checks only. Run in the existing test runner, in a clean tree, not on the author's laptop state. | WP1 | Tests added; each case has a fixture, expected checks, and a name. A documented rerun of the same fixtures gets the same result. |
| WP3 | Run that skill's evals in CI when its `SKILL.md` or fixtures change. Document the flake policy: this first set is deterministic, so it should be stable. If a later case is non-deterministic, record a noise band and do not require 100%. | WP2 | CI job is path-filtered; a deliberate break in a fixture fails the job; unrelated changes do not run the suite. |
| WP4 | Docs: a short "Evals" section in `SKILLS.md`, and a new ADR if this plan is accepted. | WP3 | Docs reviewed in the same PR. |

## Risks

- Lint noise on existing skills if warn-only checks are turned into failures too early. Mitigation: WP1 defaults to warn-only for the new checks; WP0 lists current gaps first.
- A tiny golden set gives false confidence. Mitigation: docs state the suite is a first net, not coverage of real use. Uber's 80% real-prompt band stays out until there is a human-annotated set.
- Trajectory checks that only look at "was the skill loaded" duplicate the routing gate. Mitigation: each WP2 case also checks a required command or a required output artifact, not only the load.
- Eval jobs that call a model will flake and cost money. Mitigation: option B forbids an LLM judge in this version.
- The 200-line cap and "read the skill in full on every routed edit" is a different load model from Uber's short description until invoke. Mitigation: this plan does not change the load model.

## Rollback

Remove the lint job, the eval fixtures and the CI path filter. Skills and the routing gate stay as they are. No data migration.

## Pending human decisions

1. Accept option B for WP0 to start, or keep the status quo.
2. Which two owned skills go first (`change-review` and `security` as proposed, or two others).
3. Whether missing numbered steps or an error-recovery table should fail CI, or only warn, in WP1.
4. Whether a later WP should add a human-annotated, LLM-judged set (option C), only after B is stable.
