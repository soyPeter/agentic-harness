---
name: typescript-test
description: Write or review TypeScript tests with Jest - acceptance-criterion ids in test names, behaviour through public APIs, real code over mocks (jest.mock only at port boundaries), fake timers, jsdom for components, deterministic data. Use before editing any test file or the Jest configuration.
applies-to: Jest 29+ with TypeScript (ts-jest or SWC)
last-verified: 2026-11-05
sources: Jest documentation (jest object, fake timers, test environments, test.each); the harness module-testing skill
---

# TypeScript tests (Jest)

The accepted ADRs and `backbone/7-CONVENTIONS.md` override this skill. `module-testing` holds the harness-wide rules;
this skill adds what is specific to Jest. Run the suite with `HARNESS_TEST_CMD`.

## Hard rules

1. **Each acceptance criterion's tests name its id**: `it("AC-4.1-2: rejects an upload over 10 MB", ...)`.
2. **Test behaviour through the public API**: the exported function, the handler, the rendered component.
3. **Real code over mocks.** Mock only at a port boundary the test can't own (network, clock, randomness, a
   third-party API). Prefer a fake implementing the port over `jest.mock` of a module; never mock the module under
   test or its own collaborators.
4. **Deterministic.** Fixed data, `jest.useFakeTimers()` and `jest.setSystemTime()` for time; no sleeps.
5. **Independent.** `afterEach` restores state (`jest.restoreAllMocks()`, `jest.useRealTimers()`).
6. **One behaviour per test**, Arrange, Act, Assert, asserting what a caller or user observes.

## Jest specifics

- Type the APIs with `@jest/globals` imports, or the project's configured globals.
- `test.each` for tables of inputs; `await expect(promise).rejects.toThrow(...)` for async error paths.
- Set the environment per file (`@jest-environment jsdom`) only where it differs from the config.
- Snapshot tests only for stable, reviewed output, never for whole component trees.

## Linked skills

- `module-testing`: AC traceability, test categories and coverage for any stack.
- `typescript`: the types and boundaries the tests exercise.
