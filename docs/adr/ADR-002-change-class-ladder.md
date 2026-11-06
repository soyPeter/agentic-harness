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
