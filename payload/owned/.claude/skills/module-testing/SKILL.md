---
name: module-testing
description: Write or review automated tests - acceptance-criterion traceability (AC ids in tests), Arrange-Act-Assert, one behaviour per test, determinism, test categories, test data, mocking at port boundaries and coverage. Use for any test code and when judging whether acceptance criteria are proven.
applies-to: any
last-verified: 2026-10-05
sources: adapted from cuioss/plan-marshall dev-general-module-testing (tree ce2cc13); library mandates removed, AC traceability and harness rules added
---

# Module testing

Project rules come first: the testing conventions in `backbone/7-CONVENTIONS.md`, the testing-strategy ADR and `HARNESS_TEST_CMD` / `HARNESS_TEST_PATHS` in `backbone/harness.conf`. The project's language skill names the test framework and its idioms.

## Traceability to acceptance criteria (mandatory)

The judge passes a task only when every acceptance criterion is traced to a passing test.

- Every `AC-<task>-<n>` in the spec has **at least one** test that names its id in the test name, display name, tag or a comment on the test.

  ```
  test "AC-2.1-3: rejects a customer name longer than 100 characters with 400"
  // or: @DisplayName("AC-2.1-3 ...") / it("AC-2.1-3 ...") / def test_rejects_long_name():  # AC-2.1-3
  ```
- A test **proves** its criterion only if it sets up the AC's **Given**, performs its **When**, and asserts its **Then**. Mentioning the id on a test that asserts something else is a false trace; the judge fails it.
- Test the Then at the level the AC observes it: an HTTP status and body for an API criterion, a persisted row for a storage criterion, an emitted event for a messaging criterion.
- One AC may need several tests (e.g. one per example in the AC). Each mentions the id.
- Tests that prove no AC (corner cases, unit tests of helpers) are welcome; they don't need an id.
- Never edit the spec to match the tests. If an AC cannot be tested as written, stop and report it.

## Test data

- **Use the concrete data from the acceptance criteria first.** If the AC says "given customers 'Ana' and 'ana'", the test uses exactly those values; that makes the trace obvious.
- Use generated or randomised data only for **parameter variants** beyond the AC examples (property-based or generator-based tests), with a fixed or logged seed so failures reproduce.
- Build complex objects with small factory functions that take overrides; keep the values that matter to the assertion visible in the test.
- No shared mutable fixtures. Each test creates the data it needs.

## Structure: Arrange, Act, Assert

```
test "AC-4.2-1: applies 10% discount to orders over 100 EUR" {
    order = anOrder(total = eur("120.00"))

    priced = pricing.price(order)

    assert priced.discount == eur("12.00")
}
```

- Three phases separated by blank lines; no `// Arrange` comments needed.
- **One behaviour per test**: one action in Act. Several assertions are fine when they check one outcome (group them with the framework's soft or grouped assertions).
- Names state the behaviour and condition: `rejectsExpiredToken`, `returnsEmptyPageWhenNoMatches`; never `test1` or `testValidation`.
- Assert explicitly. "No exception thrown" alone proves nothing. A test without a meaningful assertion is a defect.
- No logic in tests: no `if`, `switch`, loops that may run zero times, or try/catch (except when asserting an error with the framework's assertion).
- Test the contract (inputs, outputs, observable effects), not private methods or call order inside the unit.

## Determinism

- No `sleep` or fixed delays. For asynchronous outcomes use an await/poll utility with a timeout, or a synchronous test seam.
- No dependence on test order, shared mutable state, the wall clock, the default time zone or locale, random seeds you don't control, or the network. Inject a clock and fix the zone.
- Integration tests own their resources: a fresh container, schema or transaction per test or per class, cleaned up by the framework lifecycle.
- A flaky test is a failing test. Fix the cause; never retry it until green or mark it ignored without a recorded task.

## Categories

| Category | Scope | Doubles | Typical use |
|---|---|---|---|
| Unit | One domain or application unit, in memory | Test doubles for outbound ports only | Business rules, calculations, state transitions, validation |
| Integration | One adapter against the real technology (database, broker, HTTP client) | None for the technology under test; containers or embedded servers | Repository queries, mappings, transactions, serialisation |
| Contract | The boundary as clients see it (API, events) | The application behind it may be real or stubbed | Status codes, payload shapes, error formats, OpenAPI conformance |
| End-to-end | A deployed slice through all layers | None | A few critical user journeys |

- Prefer many unit tests and fewer, focused integration tests. Prove each AC at the cheapest level that observes its Then.
- Keep categories separable so the build can run them independently (naming, directories or tags per the project convention).

## Within each test class, cover

1. **Happy path**: the AC examples.
2. **Parameter variants**: equivalence classes of valid input.
3. **Boundaries and corner cases**: min-1, min, max, max+1; empty, blank, null or absent; very long; special characters.
4. **Errors**: invalid input, not found, conflict, permission denied, and a dependency failing or timing out.

## Mocking

- Mock only boundaries you own: the **outbound ports** (repository, gateway, clock, id generator). A hand-written in-memory fake of a port is often clearer than a mocking library.
- Never mock the unit under test, value types, domain entities or types you don't own (framework or library classes); wrap foreign APIs in an adapter behind a port and test the adapter with an integration test.
- If a test needs more than a few mocks or stubs, the unit has too many collaborators; report it as a design finding.
- Verify interactions (a call happened) only when the interaction is the observable effect, such as sending an email through a notification port.

## What not to test

- Framework or library behaviour (that the ORM saves, that the router routes) except through your own integration tests of your adapters.
- Trivial accessors, generated code, configuration constants and plain data records with no logic.
- Private methods directly; test them through the public behaviour.
- Logging output, unless the AC observes a log entry.

## Coverage

- Guide, not goal: about 80% line and branch coverage on domain and application code. Near-complete coverage on security, validation and money or state logic.
- Never write a test only to raise the number. A gap is fixed by a test that asserts a behaviour, or accepted with a reason.
- Coverage never replaces traceability: 100% coverage with an untraced AC still fails the judge.

Read `methodology.md` for boundary-value analysis, test organisation and splitting, assertion messages, async and time handling, and the anti-pattern table.

## Judge checklist

- [ ] Every AC id in the spec appears in at least one test, and that test sets up its Given, performs its When and asserts its Then.
- [ ] Each traced test passes in `HARNESS_TEST_CMD`, and its assertion would fail if the Then were not met.
- [ ] AC example data is used verbatim.
- [ ] Negative ACs have tests asserting the specified error (status, error type, message or field).
- [ ] No sleeps, order dependence, shared mutable state or uncontrolled time and randomness.
- [ ] Doubles only at outbound ports; no mocking of the unit or of foreign types.

## Linked skills

- `requirements-writing`: how ACs are phrased, so tests can mirror their Given/When/Then.
- `code-quality`: test code follows the same naming, duplication and readability rules.
- `api-design`: which statuses, bodies and headers an endpoint test must assert.
- `architecture`: which layer a behaviour lives in, and therefore which test category proves it.
- The project's language skill: the test framework, assertion library and how to name or tag tests with AC ids.
