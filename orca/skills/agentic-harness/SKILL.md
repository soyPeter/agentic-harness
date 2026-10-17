---
name: agentic-harness
description: Drive a repository that has the agentic harness installed (scripts/harness/lib/harness.py) with Orca workers without breaking its gates. Use it before coordinating, dispatching or reviewing work in such a repository.
---

# Agentic harness in Orca

The agentic harness gates every change in a repository: a task needs a valid, grilled, approved spec before it
starts, and a judge pass on its current code before it is done. The gates run in the agents' own hooks, the git
hooks and CI, so they hold whichever agent works. Your job as a coordinator is to work **with** them.

## 1. Check that it applies

```text
test -f scripts/harness/lib/harness.py && python3 scripts/harness/lib/harness.py doctor
```

No file: this skill doesn't apply. Doctor errors: report them to the user and stop.

## 2. Prefer the built-in coordinator, started by the user

The harness ships its own Orca coordinator, which follows every rule below. Agents may not start it: the hooks
refuse `harness.py orca` and `harness.py orca-nightly` from an agent, and only one runs per repository (a lock).
You may plan with it and read its results:

```text
python3 scripts/harness/lib/harness.py orca --dry-run    # what each ready task needs next (allowed)
python3 scripts/harness/lib/harness.py orca-digest       # the last finished run's summary (allowed)
```

Then ask the user to start it, in an Orca terminal of its own (a terminal coordinates one Run at a time):
`python3 scripts/harness/lib/harness.py orca --merge --trust`, or `harness.py orca-nightly`, which opens one. Scheduled
runs come from `enroll.sh --orca --automation <schedule>`: Orca's precheck starts them, not an agent. The coordinator
needs `HARNESS_AUTONOMY="autonomous"` in `backbone/harness.conf`, which only the user sets.

## 3. Rules when coordinating by hand

1. **Ask the harness, every time.** Before each step run `python3 scripts/harness/lib/harness.py next <id> --json`
   and do what it says: `step`, `role`, `command`, `questions`, `brief`. Never decide the next step yourself.
2. **One worker per step, delegating to the role.** A worker's spec names the step and the role agent it must use
   (analyst, architect, griller, tester, implementer, judge, debugger, scribe). The worker orchestrates; the role
   agent edits, and the hooks hold it to its role.
3. **Command steps go through the harness.** When `next` returns a `command` (`harness.py approve <id>`,
   `start <id>`), run it yourself, and run `harness.py finish <id>` when it says `finish`. When it returns `needed`
   instead (in supervised mode, approval is the user's `Approved-by:` line), ask the user and wait; policy approval
   exists only in autonomous mode. Never edit `backbone/3-TASKS.md`, a spec's approval line, `backbone/.verdicts/` or
   `backbone/escalations.md` to move a task along.
4. **Workers don't finish tasks.** A worker never marks a task `[x]` and never commits it. After `finish` succeeds,
   commit the task's code, tests, spec, verdicts and backbone changes together.
5. **Questions get answers with a source.** When a worker asks you something, start an analyst worker (an architect
   worker for design questions) to answer from `backbone/` and the knowledge source and record it in the spec under
   Assumptions with its source. Reply with where the answer is. A chat answer alone doesn't count.
6. **Escalate what the sources don't settle.** `python3 scripts/harness/lib/harness.py escalate <id> --reason "..."`
   parks the task for the user. Never clear a `BLOCKED` note or resolve an escalation yourself.
7. **Permission prompts belong to the user.** If a worker waits at a permission or trust prompt in its terminal,
   tell the user. Don't answer it for them.
8. **One worktree per task** when tasks run in parallel; each has its own `3-TASKS.md`. Merge finished tasks into
   the base branch before starting tasks that depend on them (`(after: 1.2)` on a task line).

## 4. Read the results

```text
python3 scripts/harness/lib/harness.py state --json      # every task: state, verdicts, approval, escalations
python3 scripts/harness/lib/harness.py questions <id>    # the griller's open questions, routed
python3 scripts/harness/lib/harness.py escalations       # what waits for the user
python3 scripts/harness/lib/harness.py report            # tasks done, verdicts, escalations, blocks, cost
```

Report outcomes as the harness records them. If a gate refused something, say which and why; don't work around it.
