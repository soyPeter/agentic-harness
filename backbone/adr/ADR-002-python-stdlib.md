# ADR-002: Python 3.8 and the standard library

## Status
Accepted

## Date
2026-11-10

## Context
This repository is the harness, and it now runs Orca against itself. The stack has to be the one the product already ships: agents and the self-test must be able to run it with nothing but git and Python. A framework, a package index or a catalog pack would become a second source of truth next to the engine.

`HARNESS_PROFILE="triple"` is set so Orca refuses `--merge`, `--trust` and `orca-nightly`. That profile is a `harness.conf` value. It does not adopt the catalog pack named `triple`.

## Decision
The stack is Python 3.8 or later and the standard library only.

- The engine, the launcher, the installer and the self-test runner stay on the standard library.
- The test command is `tests/run-tests.sh`.
- There is no build tool and no runtime service.
- No catalog pack is adopted. Stack skills are the core skills from the pinned release.
- Specs for work in this repository cite this ADR on their `ADRs:` line when they need an Accepted project ADR.

## Alternatives considered
- Adopt the `triple` catalog pack because the profile is named triple: rejected. The pack adds delivery-policy skills this repository does not use, and the profile already enforces the no-merge rule.
- Vendor the engine into `scripts/harness/` (a full install): rejected. Workers would be editing the same files that judge them. Thin mode keeps the judge on v0.30.0.

## Consequences
- A change that needs a third-party library has to become a new ADR before any import lands.
- `doctor` may warn that `HARNESS_BUILD_CMD` is empty. That is expected. The self-test is the check.
- Product decisions stay in `docs/adr/`. This ADR does not accept or replace them.
