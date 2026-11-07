# Disputes pilot runbook

A supervised first run of the harness on Disputes work: one light-lane ticket from Linear, through define, build and
judge to a receipt and a pull request that a human merges. Pedro is present for the whole first run.

## Before you start: decisions and approvals

| Decision | Options | Needed for |
|---|---|---|
| Pilot repo | A fork of `triple-disputes` under a personal account, or a throwaway demo repo | Step 1 |
| Stack packs | `typescript` and `react` (npm, Vitest, strict, Next.js, Testing Library) match `triple-disputes`; add Kotlin only if the pilot repo needs it | Step 3 |
| Linear workspace | Disputes only, or also Enrichment | Step 4 |
| CI judge | `ANTHROPIC_API_KEY` for `harness-judge.yml`, or judge locally only | Step 6 |

These need Pedro's explicit approval, every time:

- any write to a `Triple-Tech` repository (this runbook never needs one);
- any branch protection change (`enroll --protect` is refused under the profile anyway);
- autonomous mode (`HARNESS_AUTONOMY="autonomous"`);
- enrolling a real pilot repository.

## 1. Bootstrap onto the fork or the throwaway repo

Work in a fork or a sandbox, never in a clone of `Triple-Tech/triple-disputes` that has its remote as `origin`.

```sh
git clone git@github.com:<you>/triple-disputes.git ~/Work/pilot/triple-disputes     # or: mkdir demo && git init
cd ~/Work/pilot/triple-disputes && git remote -v                                     # origin must be the fork
~/Work/repos/agentic-harness/enroll.sh . --profile triple --dry-run                  # read the plan first
~/Work/repos/agentic-harness/enroll.sh . --profile triple
git config core.hooksPath scripts/harness/git-hooks
```

Don't pass `--automation` or `--protect`: the profile refuses them before changing anything. Commit the install with
`HARNESS_VERIFY=off git commit -m "chore: adopt agentic harness"`, because the profile line is a user-only setting.

Check the profile holds:

```sh
python3 scripts/harness/lib/harness.py orca --merge      # must print: refused under HARNESS_PROFILE=triple
python3 scripts/harness/lib/harness.py doctor
```

### Fitting into triple-disputes

`triple-disputes` already has its own agent files and git hooks. Before the first session:

- **`AGENTS.md`**: the installer keeps the repository's own and writes the harness's next to it as
  `AGENTS.md.harness-new` (reported as a CONFLICT). Move the Disputes agent rules into `backbone/7-CONVENTIONS.md`
  (conventions) and `backbone/4-KNOWLEDGE.md` (stack, NEVER DO). Then replace `AGENTS.md` with the `.harness-new` file
  and run `update.sh status` again.
- **`CLAUDE.md`** stays the project's. Add `@AGENTS.md` as its first line, or no session loads the harness rules. It
  is one line against the `check:claude-md-size` budget.
- **Git hooks**: Husky owns `core.hooksPath` (`.husky/_`). Keep it, and chain the harness hooks instead of switching
  `core.hooksPath`:

  ```sh
  printf '\nscripts/harness/git-hooks/pre-commit\n' >> .husky/pre-commit
  printf 'scripts/harness/git-hooks/commit-msg "$1"\n' > .husky/commit-msg
  printf 'scripts/harness/git-hooks/pre-push "$@"\n' > .husky/pre-push
  ```

  Doctor accepts chained hooks and names any hook that doesn't hand on.
- **Build check**: Husky's pre-commit already runs `npm run typecheck`. Leave `HARNESS_BUILD_CMD` empty after adopting
  the `typescript` pack, so the type check doesn't run twice.
- **Conventions the harness doesn't know**: commits on the task branch follow Conventional Commits (the harness's
  commit-msg hook); the PR title follows CONTRIBUTING (`DIS-<n>: <the outcome>`), because the PR is squash-merged.
  Write both into `7-CONVENTIONS.md` so the deliverer reads them. The repository's own specs live outside it: cite
  the one a task follows in its harness spec's Context.

## 2. First-run setup (supervised)

Start an agent session. It reports SETUP INCOMPLETE and walks through `AGENTS.md` section 1 with you:

- `4-KNOWLEDGE.md`: the stack as it is, and a NEVER DO list that names the parked surfaces;
- `HARNESS_BUILD_CMD` and `HARNESS_TEST_CMD`: the repo's own commands (for example `pnpm build`, `pnpm test`);
- `ADR-002`: the pilot decision. It names the `triple` pack with `disputes-pci` and `ears`, and the `typescript` and
  `react` packs with their options. You accept it.

## 3. Adopt the packs

```sh
python3 scripts/harness/lib/harness.py adopt triple --adr ADR-002 --with disputes-pci,ears
python3 scripts/harness/lib/harness.py adopt typescript,react --adr ADR-002 \
        --with npm,vitest,strict,nextjs,testing-library          # the triple-disputes stack
```

Paste `scripts/harness/catalog/triple/tools.conf.linear` into `backbone/tools.conf`. Switch on the light lane for the
pilot (`HARNESS_LIGHT_LANE="on"` in `harness.conf`, user-only). Commit.

## 4. Import one light-lane ticket

Pick a `DIS-*` ticket that touches only UI or docs: no parked path, nothing the `disputes-pci` skill lists.

```sh
export LINEAR_API_KEY=<personal key>
python3 scripts/harness/lib/harness.py linear import DIS-<n> --task 1.1 --light --dry-run
python3 scripts/harness/lib/harness.py linear import DIS-<n> --task 1.1 --light
python3 scripts/harness/lib/harness.py risk 1.1          # must be low-risk, or the light lane won't apply
```

## 5. Define, build, judge (supervised)

In the agent session, ask the orchestrator to run task 1.1. It follows `harness.py next`:

1. **Analyst.** Writes the EARS requirements and Given/When/Then criteria from the quoted ticket. `spec-check 1.1`
   must pass.
2. **Approval.** You read the spec and add `Approved-by: <name> (<date>)`. Light lane: no architect, no griller.
3. **Implementer.** Changes the code with tests that name the AC ids.
4. **Judge, then the three reviewers.** A fail goes to the debugger and back to the implementer. After
   `HARNESS_JUDGE_MAX_ROUNDS` fails, stop and decide.
5. **Commit.** Through the git hooks, without `--no-verify`.

Stop the run and escalate if any step needs a parked path. The guardrails refuse the edit, and the skill names the
owner.

## 6. Receipt and pull request

```sh
python3 scripts/harness/lib/harness.py receipt 1.1
python3 scripts/harness/lib/harness.py linear receipt 1.1 --status "In Review" --dry-run
python3 scripts/harness/lib/harness.py linear receipt 1.1 --status "In Review"
```

The deliverer pushes the branch to the fork and opens the PR, with the receipt in it, then watches CI. It also adds the
receipt's suggested `risk:*` and `class:*` labels and creates the ones the repository lacks, which is a write to that
repository; without permission it says so and delivers anyway. **A human reviews and merges.** The harness can't:
`gh pr merge` and MCP merge tools are refused under the profile, and the receipt never closes the Linear ticket.

## 7. Metrics

Record these after each pilot task:

| Metric | Source |
|---|---|
| First-pass judge accept | `harness.py report`: "first-pass judge rate" |
| Escalations by class | `harness.py report` ("by class") and `harness.py escalations` |
| Cost per accepted PR | `harness.py report`: "cost per finished task" for runner sessions; otherwise the agent's own usage |
| Human review minutes | By hand: minutes Pedro spent reading the spec, the receipt and the PR |

Look at `backbone/proposals/` after the run. A failure class that recurred has a draft proposal there for you to
accept, edit or drop.

## Not in the pilot

Autonomous mode, `orca --merge`, scheduled runs, PCI surfaces, and any change to `Triple-Tech` repositories. The
`harness-agent` devcontainer is not a PCI attestation.
