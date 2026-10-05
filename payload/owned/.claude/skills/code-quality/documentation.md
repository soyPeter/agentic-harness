# Code documentation

Part of the `code-quality` skill. The project's language skill gives the doc-comment syntax (Javadoc, KDoc, JSDoc/TSDoc, docstrings, rustdoc).

## What must be documented

- Every public or exported type, interface, module and function, including port interfaces (document the contract the adapter must honour).
- Every parameter: purpose and constraints (non-null, range, format, units).
- The return value: what it represents and its guarantees (never null, sorted by, empty when).
- Every error or exception the caller can observe, and when it occurs.
- Public constants and configuration keys: meaning, units and default.
- Complex algorithms or business rules, whatever their visibility: reference the requirement (`REQ-<task>-<n>`) or ADR they implement.
- Thread-safety for types used concurrently: safe or not, what callers must synchronise, lock ordering.
- Deprecations: what replaces it and when it will be removed.

## What not to document

- Private helpers whose name and signature say everything.
- Trivial accessors, record components and fields whose type and name are self-explanatory.
- Functions that only delegate without adding behaviour.
- Loggers, serial ids and similar boilerplate.
- Implementation details that callers must not rely on.

## How to write it

- First sentence states the purpose in the present tense, active voice: "Calculates the shipping cost for an order." Do not repeat the name ("Gets the cost").
- Document the **contract**, not the implementation. Callers need to know behaviour, inputs, outputs and failures, not which data structure is used.
- Be short and specific. Replace "processes the data" with what is processed, how, and with what result.
- Use the spec's domain terms consistently across the codebase.
- Add a usage example only for APIs that are hard to use correctly; keep it compiling or tested.

```
// vague
Validates a token.
  token: the token
  returns: the result

// contract
Validates the token's signature and expiry against the configured issuer,
allowing the configured clock skew.
  token: the encoded token; must not be empty
  returns: Valid, or Invalid with the reasons
  errors: IssuerUnavailable when the issuer's keys cannot be fetched
```

## Comments inside code

- Explain **why**, never what: constraints, trade-offs, non-obvious ordering, workarounds with their cause.

  ```
  // noise
  // duration of 30 seconds
  CLOCK_SKEW = seconds(30)

  // why
  // Issuer and verifier clocks drift by up to 30 s in production (see ADR-007).
  CLOCK_SKEW = seconds(30)
  ```
- If a comment explains what confusing code does, rename or extract instead: `if user.hasAdminRights() and action.isAllowedFor(user.role)` beats a comment above `if (role == 1 || role == 2) && (action in [3, 4, 7])`.
- Warnings are welcome when they prevent a mistake: "Order matters: discounts before tax (REQ-3.2-4)."
- `TODO` and `FIXME` carry a task id or issue reference; otherwise record the item in `backbone/6-MEMORY.md` or `3-TASKS.md` instead.
- Never leave commented-out code; version control keeps history.

## Keeping docs true

- Wrong documentation is worse than none. Update docs in the same change as the behaviour or signature.
- Update when: a signature changes, behaviour or error semantics change, a public API is added or deprecated, or a bug fix changes documented behaviour.
- Within the task's scope, fix stale docs you touch. Stale docs outside the scope are recorded, not fixed (see the scope rule in `SKILL.md`).
- Run the language's doc tool or linter if the project configures one; broken references fail the review.

## Module and project docs

- A module README (if the project uses them) states the module's responsibility, its public entry points and its dependencies. Architecture decisions belong in ADRs, not READMEs.
- API contracts are documented in the OpenAPI file (openapi skill), not duplicated in prose.
