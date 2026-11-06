# EARS requirements

Used when `HARNESS_REQ_STYLE="ears"` in `backbone/harness.conf` (the session-start note says so). `spec-check`
rejects a requirement that doesn't follow one of these patterns. Ids stay `REQ-<task>-<n>`: they are the stable EARS
ids that acceptance criteria, tests, verdicts and receipts trace.

| Pattern | Template | Example |
|---|---|---|
| Ubiquitous | The `<system>` shall `<response>`. | The case list shall show each case's status. |
| Event-driven | When `<trigger>`, the `<system>` shall `<response>`. | When an agent opens a case, the case view shall show its evidence. |
| State-driven | While `<state>`, the `<system>` shall `<response>`. | While a case is locked, the case editor shall reject edits with 409. |
| Unwanted behaviour | If `<condition>`, then the `<system>` shall `<response>`. | If an evidence file exceeds 10 MB, then the upload form shall reject it with "File too large". |
| Optional feature | Where `<feature>`, the `<system>` shall `<response>`. | Where CSV export is enabled, the case list shall offer a download. |
| Complex | While `<state>`, when `<trigger>`, the `<system>` shall `<response>`. | While a case is open, when its deadline passes, the case list shall mark it overdue. |

What `spec-check` refuses:

- **No `shall`**, or more than one: one response per requirement. Split compound requirements.
- **No system**: `shall` needs a named actor before it ("the case list shall", not "cases shall be listed").
- **Missing trigger, state or condition**: `When`, `While`, `If` and `Where` need their clause and a comma before the
  system. `If` takes `then`.
- **Passive voice** ("shall be sent"): say which system acts and what it does.
- **Untestable words**: appropriate, adequate, user-friendly, easy, fast, quickly, efficient, as needed, if possible,
  etc., and/or, robust, seamless, intuitive, flexible, sufficient, reasonable, be able to. Replace them with a number,
  a list or an observable result.

## Acceptance criteria as the evidence layer

Each EARS requirement still gets Given/When/Then acceptance criteria, one per scenario: the judge traces them to
tests. Map them 1:N: every requirement has at least one criterion, and every criterion names the requirement(s) it
proves. A criterion may also prove a non-functional requirement: give NFRs ids (`- NFR-<task>-1: ...`) and cite them
(`AC-<task>-3 (NFR-<task>-1): ...`). Write the EARS trigger as the When of its main criterion, so the two read the same.
