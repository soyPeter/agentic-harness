---
name: change-review
description: Review of a task's change through one of three lenses (correctness, structure, lean) that run in parallel, each finding backed by a concrete failing case and graded must-fix, should-fix or nice-to-have. Use after the judge passes a task, before it is finished; the reviewer runs it once per lens.
applies-to: any
last-verified: 2026-11-03
sources: thermo-nuclear-review and thermo-nuclear-code-quality-review (cursor/plugins thermos @ae5650f, MIT); blast-radius and principle-prove-it-works (cursor/plugins pstack 0.15.36 @ae5650f, MIT, Lauren Tan); ponytail-review (DietrichGebert/ponytail @96608e0, MIT). Licences in NOTICE.md.
---

# Change review

The judge has checked the task against its spec. This review looks at what a spec check misses: what the change breaks outside the diff, the shape it leaves the codebase in, and code nobody needs. Review it as the developer who gets paged when it breaks.

Three reviewers run at once, one per lens. Review **only through your lens**; the other two are covered. Read the shared sections (scope, checks, severity, reporting) and your lens section.

## Scope

- The change is the `[WIP]` task's work: `git diff HEAD`, the untracked files, and the commits already made on the task (`git log`). Review only code it **adds or modifies**. Problems in untouched code are out of scope unless the change makes them reachable.
- Read the diff, then the code around it: the callers of every changed function, the functions it calls, the tests, the README.
- Find the expected load in the repo (PRD, README, deploy config) and judge scale against it. Say which load you assumed.
- An intended breakage is not a finding when the spec or an ADR says so and its reach is contained. Report it anyway if the author seems to miss how far it reaches.
- The review changes no files. Scratch scripts go under the system temp directory and are deleted afterwards.

## Lens: correctness

Bugs, security, blast radius and missing tests. Trace side effects across modules; a small change in one place often breaks another.

- **Bugs:** wrong results, crashes, missed edge cases (empty, zero, last item, rounding, time zones, encodings), a caller the change breaks, a fix applied in one caller while the shared function stays broken.
- **Security:** injection, missing authorisation or input checks, secrets in code or logs, weak randomness, unsafe deserialisation. Load the `security` skill for the checklist.
- **Data:** swallowed errors, writes in the wrong order, partial updates without a transaction, migrations that can't run twice.
- **Scale:** fine for one user, wrong for many: check-then-write races, lists that only grow, a query per item, O(n²) on big input.
- **Devex breaks:** renamed or new environment variables, moved secrets, remapped ports, a new manual step to build or run.
- **Gate leaks:** behaviour meant to sit behind a feature flag, a role check or an internal-only path that now reaches everyone.
- **Missing test:** risky new logic (a branch, a parser, money, security, data writes, a bug fix) with no test that fails when it breaks. Ask for one good test, not coverage (`module-testing`).

**Blast radius.** Listing callers is not the job; grep does that in a second. The job is the breakage grep won't show.
1. Find the **one fact** the change is safe because of, for example "this only drops cache entries nothing reads". If it holds, most risks clear at once.
2. Look where grep stops: the pinned library's own source, JSON a client parses, a DB column, a wire format, another language reading the same bytes, teardown and ordering, code three hops away.
3. **Prove the fact by running real code**: a short script or test that calls the real function and fails loudly if you are wrong. Quote its output. Grade every safety claim by how far it got:
   1. asserted (worthless alone);
   2. pointed at: a real `file:line`;
   3. walked through: the bad case shown not to be reachable;
   4. run: a script or test against the real code;
   5. reproduced in the running app.

   Say where each claim stopped. A claim below level 3 is `unproven`.

## Lens: structure

Push for the "code judo" move: a restructuring that keeps the behaviour and makes whole branches, modes or layers disappear. Rearranging the same complexity is not enough.

- A file the change pushes from under 1000 lines to over 1000: ask for the split first.
- Spaghetti growth: ad-hoc conditionals, one-off booleans or nullable modes bolted onto an unrelated flow. Move the logic behind its own function, type or module instead.
- Logic in the wrong layer: feature logic leaking into shared code, or internals leaking through an API. Check `architecture` and the ADRs for where it belongs.
- Thin wrappers, identity abstractions and pass-through helpers; magic generic handling that hides a simple data shape.
- Casts, `any`, needless optionality or silent fallbacks that hide an invariant a typed boundary would state.
- Independent work done in sequence for no reason; related updates that can leave state half-applied.
- Refactors that move complexity around without reducing the concepts a reader must hold.

## Lens: lean

Every line has to be read, tested and fixed later.

- **delete:** dead code, unused options, speculative features, config nobody sets.
- **reuse:** the repo already has this helper; name its path.
- **stdlib:** the standard library or platform already does it, or a new dependency was added for a few lines.
- **yagni:** an abstraction with one implementation.
- **merge:** near-copies that must change together.
- **split:** one function doing unrelated jobs. Split by job, never by line count.
- **tests:** tests that repeat each other or the acceptance tests.
- **speed:** a big slowdown is should-fix; work repeated in a hot loop is nice-to-have.

A shortcut whose comment names its limit (`shortcut:`) is a decision, not a finding, unless the expected load already crosses it.

## Check before you report

- **Every finding needs a concrete case:** this input or this situation leads to this wrong result. No case, no finding.
- Re-read the lines: the caller exists, the value can be empty, the code is unused.
- Finish the research before you report. "The client has X, unless the server handles it" is unfinished when you can read the server.
- Propose the smallest fix that works, and prefer one that deletes code. Never add layers, frameworks or configuration the problem doesn't need.
- No style taste, no "consider", no vague worries. Don't inflate severity: a reviewer who cries wolf gets ignored.

## Severity

- **must-fix:** a bug, a security hole, data loss, an unintended devex break or gate leak, something that fails at the expected load; or a structural regression: a file pushed past 1000 lines, spaghetti in a shared flow, logic in the wrong layer.
- **should-fix:** risky code without a test, a real slowdown, duplication, a function mixing jobs, code that shouldn't exist, a missed code-judo move.
- **nice-to-have:** a small speed-up, a shorter form.

A must-fix finding fails the lens: the harness records a fail whatever verdict you claim, and the task goes back to the implementer. Should-fix and nice-to-have findings travel to the PR as follow-ups.

## Reporting a finding

Each finding has these parts, each one or two plain sentences:

- **Where:** `file:line`.
- **Problem:** the concrete case that goes wrong.
- **Fix:** the smallest change, with the code when it is short.
- **If we skip it:** what the user or the team will see.
- **Owner:** `implementer` for code and tests, `tester` for an acceptance test, `analyst` for a spec gap, `user` for a decision only a human can take.

## Linked skills
- `security`: the checklist behind the correctness lens.
- `module-testing`: what counts as a test that would catch the bug.
- `code-quality`: the project's code rules that the structure lens enforces.
- `architecture`: where logic belongs, for the wrong-layer findings.
