# Testing methodology details

Part of the `module-testing` skill. Read `SKILL.md` first; this file adds techniques and reference tables.

## Boundary-value analysis

For any value with a valid range `[min, max]`, test:

| Input | Expected |
|---|---|
| min - 1 | rejected |
| min | accepted |
| max | accepted |
| max + 1 | rejected |

Add `min + 1` and `max - 1` when the boundary logic is non-trivial (off-by-one risk in loops or slicing). When the AC names a limit ("names longer than 100 characters are rejected"), the boundary tests use exactly that limit (100 accepted, 101 rejected) and mention the AC id.

## Equivalence partitioning

Split the input space into classes the code treats the same way, and test one representative of each:

- each valid class (e.g. domestic order, EU order, non-EU order);
- each invalid class (malformed, out of range, missing, wrong type);
- the boundaries between classes (above).

## Corner-case checklist

- Absent values: null, undefined, missing field, empty optional.
- Empty: empty string, blank (whitespace only), empty collection or map.
- Size: one element, many elements, a page exactly full, the maximum page size, very long strings.
- Characters: Unicode (accents, non-Latin scripts, emoji), control characters, leading and trailing whitespace, case variants ('Ana' vs 'ana').
- Numbers: zero, negative, maximum, precision and rounding (money), overflow.
- Time: midnight, end of month, leap day, DST transition, different zones, clock skew.
- Concurrency: two updates to the same record (optimistic locking, 409), duplicate submissions (idempotency key).
- Dependencies: timeout, connection refused, error response, malformed response, partial failure.

## Organising tests

- At least one test file per production unit that has behaviour, mirroring its package or directory in the test source root and following the framework's naming (`<Name>Test`, `<name>.test.ts`, `test_<name>.py`).
- Split a test file that grows past about 300 lines into focused files, e.g. `<Name>Test`, `<Name>ValidationTest`, `<Name>IntegrationTest`.
- Group three or more related tests with the framework's nesting construct (`describe`, nested classes, test classes per scenario). Do not nest one or two tests.
- Name groups after the scenario or the AC ("when the customer already exists"), so traceability reads naturally.
- Shared helpers (factories, fakes, custom assertions) live in a test-support location, not copied between files.

## Assertions

- Prefer specific assertions over boolean ones: `assertEquals(expected, actual)` / `expect(actual).toEqual(expected)` instead of `assertTrue(actual == expected)`, so failures show both values.
- Assert the whole relevant outcome: status **and** body **and** relevant headers for an API; the returned value **and** the persisted state when both are part of the Then.
- When a failure message adds information, describe the expectation: "discount should be 10% of 120.00".
- For collections, assert size and content together, and assert order only when the AC specifies an order.
- For errors, assert the type and the distinguishing detail (error code, field name), not the full human-readable message unless the AC specifies it.

## Asynchronous code and time

- Inject time (a clock port or parameter) and control it in tests; never wait for real time to pass.
- For eventual outcomes (a message consumed, a projection updated), poll the observable result with an await utility: short poll interval, explicit timeout, and an assertion as the condition.
- Prefer driving asynchronous handlers synchronously in unit tests (call the handler directly) and keep real asynchrony for integration tests.
- Executors and schedulers are injectable so tests can use a same-thread or manually advanced implementation.

## Test doubles

| Double | Use |
|---|---|
| Fake | Working in-memory implementation of a port (e.g. a map-backed repository). Best default for outbound ports. |
| Stub | Returns canned answers; for queries. |
| Mock or spy | Records calls; only when the call itself is the observable effect. |
| Real object | Value types, entities, domain services without I/O. Always preferred. |

A fake used across many tests should itself be checked against the same contract tests as the real adapter, so they cannot drift.

## Integration test hygiene

- Use the same database engine and version as production (e.g. a container), not a different embedded engine, when the code uses engine-specific SQL.
- Apply the real schema migrations before the tests.
- Isolate data per test: transaction rollback, truncation, or unique keys per test. Never rely on data left by another test.
- Keep external third-party services out of automated tests; stub them at the HTTP level or behind the gateway port.

## Measuring effectiveness

- Coverage shows what ran, not what was checked. Mutation testing (where the stack has a tool) shows whether assertions would catch a change; use it on critical logic if the project configures it.
- A healthy suite breaks when behaviour changes and survives refactoring; tests that break on every refactoring are coupled to implementation.

## Anti-patterns

| Anti-pattern | Problem | Fix |
|---|---|---|
| Untraced AC | Judge cannot confirm the criterion | Name the AC id in the test that proves it |
| False trace | Test names an AC but asserts something else | Assert the AC's Then with its Given and When |
| Assertion-free test | Passes while verifying nothing | Assert the outcome |
| Logic in tests | Hides which path ran | One path per test; separate tests per case |
| Fixed sleeps | Slow and flaky | Await/poll utility with timeout, or injected clock |
| Shared mutable fixture | Order-dependent failures | Fresh data per test |
| Over-mocking | Tests prove the mocks, not the code | Fakes at outbound ports; real domain objects |
| Mocking foreign types | Breaks on library upgrades, hides misuse | Adapter behind a port plus integration test |
| Testing private methods | Brittle on refactoring | Test through public behaviour |
| Coverage-driven tests | False confidence | Test behaviours; accept justified gaps |
| Ignored flaky test | Silent loss of protection | Fix the cause or record a task |
