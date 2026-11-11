# ADR-002: Change-class ladder and human PR merge

## Status
Accepted

## Date
2026-11-06

## Context
The harness already gates work with locked specs, grill/judge verdicts, `HARNESS_RISK_TERMS` /
`HARNESS_RISK_PATHS` / `HARNESS_RISK_MAX_FILES`, an optional light lane (`HARNESS_LIGHT_*`), and
policy spec approval (`HARNESS_AUTO_APPROVE=low`). Risk is still effectively binary (low vs not),
and the light lane is a user mark rather than an explicit change class.

Factory design work (vault notes on Warp, Bhati Verification Tax / PQC, Netguru human gates,
Zalando merge-risk) asks for a **change-class ladder**: different gates and verification depth for
docs, refactors, features, and schema/auth/payments work. Without that, low-risk policy approval
and the light lane are easy to over-apply, and high-assurance changes look the same as a README fix.

Separately: GitHub PR **auto-merge** must not be confused with `Approved-by: policy:…` on a spec.
The deliverer already never merges; this ADR locks that as policy, not only as current code.

## Decision
1. **Declare a Change-Class on every task spec** (field `Change-Class:`). Allowed values:
   `docs` | `refactor` | `feature` | `schema`. If omitted, treat as `feature` (conservative default).
2. **Class → gates** (v1 semantics; enforcement in `harness.py` may land in a follow-up PR):

   | Class | Typical work | Light lane | Policy `approve` (autonomous) | Human `Approved-by` | Verify |
   |---|---|---|---|---|---|
   | `docs` | markdown, comments, non-runtime docs | allowed when light rules pass | allowed when `risk_reasons` empty | optional if policy approved | project checks that apply |
   | `refactor` | rename/extract with no behaviour change | allowed when light rules pass and no `RISK_PATHS` | allowed only when low-risk | required if not policy-approved | full build/test + fingerprint |
   | `feature` | new or changed REQ/AC | not for policy; light only if user marked and rules pass | **never** | **required** | full DEFINE→JUDGE→review |
   | `schema` | migrations, auth, secrets, payments, deploy/infra paths | **never** | **never** | **required** | full + security skill; escalate on doubt |

   `schema` covers paths/terms already hinted by `HARNESS_RISK_PATHS` / `HARNESS_RISK_TERMS`
   (auth, security, migrations, infra, deploy, openapi, credentials, tokens, …).

3. **PR merge stays human.** Deliverer may push and open/update PRs and watch CI. It never merges.
   Spec policy approval is not GitHub merge approval. No GitHub auto-merge in v1.
4. **Optional process links** on the spec (`Parent-CHNG:`, `Parent-RFC:`, `Parent-ADR:`) point at an
   external vault or design record. The harness does **not** embed a CHNG folder; the vault (or
   project ADRs under `backbone/adr/`) remains the system of record for process artifacts.
5. **EARS stays opt-in** via `HARNESS_REQ_STYLE=ears` (already implemented). This ADR does not make
   EARS mandatory.

## Alternatives considered
- **Keep binary risk + light lane only:** cheapest, but classes stay implicit and easy to misuse for
  high-assurance changes; does not document the factory ladder we intend to enforce later.
- **Many fine-grained classes (docs/chore/refactor/feature/api/db/payments/auth/…):** more precise,
  but higher authoring cost and fuzzy boundaries; four classes cover the PQC split we need now.
- **GitHub auto-merge for `docs`/`refactor` low-risk (Zalando-style):** attractive for lead time, but
  needs a measured V_tax / false-approve baseline first; out of scope for v1 while deliverer must
  never merge.

## Consequences
- Spec template and `requirements-writing` skill teach Change-Class and optional Parent-* links now.
- `harness.py` should eventually parse `Change-Class:` and fold it into `risk_reasons()`, light-lane
  eligibility, and `approve`. Until that ships, analysts/grillers/humans still declare the class;
  mis-declaration is a process failure, not yet a hard gate.
- Follow-ups (not this change): (a) enforce Change-Class in `risk_reasons` / `approve` / light lane;
  (b) emit suggested `risk:*` labels from `receipt` for human PR triage; (c) eval/replay fixtures
  from `report` lift/candidates.
- Seeded project ADR-001 ("Adopt the agentic harness") is unrelated numbering: product ADRs live
  under `docs/adr/` in this repository.

## Amendment: follow-up (c), eval and replay fixtures (added 2026-11-11)
Added on 2026-11-11. Status stays Accepted; the decision above is unchanged.

**How (c) was decided.** The report's candidates were plain strings, and a refusal logged only its reason, so no past
refusal could be replayed. Follow-up (c) was cut down to the deterministic gates: their answer depends only on the
hook input and the rules, so a fixture can be replayed exactly, with no model calls. The rest of policy replay and
shadow evaluation stays with [ADR-007](ADR-007-evidence-closed-loop.md) (Proposed), which asks for resettable
fixtures, a pinned harness and an evaluator whose expected outcomes are independent of the builder. In v1 the fixtures
are the user's: agents only draft them.

**What v1 covers.**
- Capture: a refused `pre-tool-use` call, and a bounded sample of allowed ones per gate, is kept in `.git/harness/`
  with its input redacted and size-capped, its settings fingerprint, and whether its outcome is state-free or
  state-dependent, with why.
- Candidates: `harness.py report --json` gives each one an id, kind, reason, tasks and the captured inputs behind it.
- Fixtures: `harness.py eval export` drafts reviewable fixtures into `backbone/proposals/evals/`. `backbone/evals/` is
  user-owned like `tools.conf`: the hooks refuse agents' writes to it, and verify refuses a commit that changes it
  unless the user makes it (`HARNESS_VERIFY=off`, or the `harness-change-approved` label in CI).
- Replay: `harness.py eval replay [--engine <harness.py>]` runs the state-free fixtures through `hook pre-tool-use` in a
  throwaway checkout, and exits non-zero on a hole (a refusal now allowed), a false block (an allowed call now
  blocked), a changed refusal reason or an error. Judge-fail and escalation candidates are exported as eval prompts and
  not replayed.

**Left for later.**
- Running the replay in CI, in the self-test and in `harness-verify` with the base branch's engine against the pull
  request's, so a rule or engine change that reopens a past refusal or blocks a past allow shows on the pull request.
  Today it runs locally with `--engine`.
- Replaying state-dependent refusals (task, spec, verdict and skill state).
- Model-based replay, eval prompts and shadow candidates, per ADR-007.
