---
name: typescript-test
description: Write or review TypeScript tests with Vitest - acceptance-criterion ids in test names, behaviour through public APIs, real code over mocks (vi.mock only at port boundaries), fake timers, happy-dom or jsdom for components, deterministic data. Use before editing any test file or the Vitest configuration.
applies-to: Vitest 2+ with TypeScript
last-verified: 2026-11-05
sources: Vitest documentation (vi, fake timers, environments, test.each); the harness module-testing skill; written for the Triple Disputes pilot
---

# TypeScript tests (Vitest)

The accepted ADRs and `backbone/7-CONVENTIONS.md` override this skill. `module-testing` holds the harness-wide rules;
this skill adds what is specific to Vitest. Run the suite with `HARNESS_TEST_CMD`.

## Hard rules

1. **Each acceptance criterion's tests name its id**: `it("AC-4.1-2: rejects an upload over 10 MB", ...)`. The judge
   traces criteria to tests by that id.
2. **Test behaviour through the public API**: the exported function, the route handler, the server action, the
   rendered component. Don't import private helpers to test them, and don't assert on internal calls.
3. **Real code over mocks.** Mock only at a port boundary the test can't own: the network, the clock, randomness, a
   third-party API. Prefer a fake that implements the port (an in-memory repository, a local HTTP server) over
   `vi.mock` of a module. Never mock the module under test or its own collaborators.
4. **Deterministic.** Fixed data, `vi.useFakeTimers()` and `vi.setSystemTime()` for time, seeded randomness. No sleeps:
   advance fake timers, or await the condition.
5. **Independent.** Each test sets up what it needs. `beforeEach` restores state (`vi.restoreAllMocks()`,
   `vi.useRealTimers()`); no order dependence, no shared mutable fixtures.
6. **One behaviour per test**, in Arrange, Act, Assert order. Assert what a user or caller observes: the return value,
   the response status and body, the rendered text, the persisted row.

## Vitest specifics

- Import APIs explicitly (`import { describe, it, expect, vi } from "vitest"`) unless the config enables globals.
- `test.each` for tables of inputs; name each case by its data.
- `expect.assertions(n)` or `await expect(promise).rejects.toThrow(...)` for async error paths, so a test can't pass
  without running its assertion.
- Components run in the environment the config sets (`happy-dom` or `jsdom`); set it per file with
  `// @vitest-environment happy-dom` only where the default differs.
- Snapshot tests only for stable, reviewed output (a serialized document format), never for whole component trees.
- Integration tests that need a database or a container are tagged or kept in their own config, so the fast suite
  stays fast; say in the spec which suite proves which criterion.

## Linked skills

- `module-testing`: AC traceability, test categories and coverage for any stack.
- `typescript`: the types and boundaries the tests exercise.
