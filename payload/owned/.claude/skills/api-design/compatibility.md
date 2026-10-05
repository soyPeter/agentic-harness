# API compatibility, deprecation and contract review

Part of the `api-design` skill. The project's API and versioning ADRs override these defaults.

## Breaking vs non-breaking changes

A change is breaking if an existing, correctly written client can fail or misbehave without changing its code.

| Change | Breaking? | Migration |
|---|---|---|
| Add an endpoint | No | Document it in the contract |
| Add an optional request field or query parameter | No | Default must keep the old behaviour |
| Add a response field | No* | *Breaking only for clients that reject unknown fields; document that clients must ignore them |
| Add an enum value to a response | Often | Clients with exhaustive switches break; announce it, or document that clients must tolerate unknown values |
| Remove an endpoint | Yes | Deprecate with headers and docs, keep it until the sunset date, then remove in a new version |
| Remove or rename a response field | Yes | Keep the old field (populated) alongside the new one until sunset |
| Add a required request field | Yes | Make it optional with a server-side default; require it only in the next version |
| Change a field's type or format | Yes | Add a new field with the new type; deprecate the old |
| Change a field's meaning or units | Yes | New field name; never silently reuse a name |
| Tighten validation (shorter max, narrower enum) | Yes | Apply only to new versions, or after a deprecation period with warnings |
| Change a status code or error format | Yes | New version; keep the old behaviour in the current one |
| Change the URL path | Yes | Keep the old path, redirect (308 for non-GET) or proxy it until sunset |
| Change default sort order or page size | Yes | Treat as breaking; announce it, or let clients request the new behaviour explicitly |
| Change authentication or required scopes | Yes | Overlap period in which both work |
| Loosen validation, add optional behaviour | No | Document it |

Every breaking change needs: a new version (`/v2` path or versioned media type, per the ADR), an ADR, an updated contract, and a **BREAKING** changelog entry.

## Deprecation

1. **Decide and record**: deprecation date, sunset (removal) date, replacement, in an ADR or the API changelog. Give clients a timeline long enough for their release cycles (state it, e.g. at least one or two of their release cycles, or the period the project's ADR sets).
2. **Mark in the contract**: `deprecated: true` on the operation, parameter or schema property in OpenAPI, with a description naming the replacement and the sunset date.
3. **Signal at runtime** on every response from the deprecated resource:

   ```
   Deprecation: @1767225599
   Sunset: Thu, 31 Dec 2026 23:59:59 GMT
   Link: <https://api.example.com/docs/deprecations/v1-orders>; rel="deprecation"; type="text/html"
   ```

   - `Deprecation` (RFC 9745) is a structured-field date: `@` followed by Unix seconds of when the resource is (or was) deprecated.
   - `Sunset` (RFC 8594) is an HTTP-date of when the resource may stop responding. It must not be earlier than the `Deprecation` date.
   - The `deprecation` link relation points to human-readable migration docs.
4. **Communicate**: release notes, the changelog `Deprecated` section, and direct notice to known consumers.
5. **Monitor** usage of the deprecated resource (log or metric per client) before removing it.
6. **Remove** after the sunset date, in the new version; the old one then returns 410 Gone (or 404) with a problem body pointing to the replacement, if the project keeps a tombstone.

## Contract review recipes

Review the contract (OpenAPI file) and the code that implements it.

### Compare contract versions

```bash
git diff <last-release-tag> -- <path/to/openapi.yaml>
```

If the project has an OpenAPI diff tool (for example `oasdiff` or `openapi-diff`), run it between the released and the current contract and treat every reported breaking change as needing the rules above.

Read the diff for: removed paths or operations; removed or renamed properties; new entries in `required`; changed `type`, `format`, `enum`, `minLength`/`maxLength`, `minimum`/`maximum`, `pattern`; changed status codes; changed `security`.

### Find typical defects in code (adapt globs and names to the stack)

```bash
# Verbs in paths
grep -rnE '"/(get|create|update|delete|fetch|do)[A-Z_-]' <api layer dir>

# Unversioned public routes (if the ADR requires a version prefix)
grep -rnE '"/api/[a-z]' <api layer dir> | grep -vE '/v[0-9]+/'

# Persistence entities or ORM types returned from the API layer
grep -rnE '(Entity|Record|Model)\b' <api layer dir>

# Success status carrying an error body
grep -rniE '(ok|200).*(error|fail)' <api layer dir>

# Stack traces or exception messages written to responses
grep -rnE '(printStackTrace|stack|getMessage\(\)|\.message)' <api layer dir>
```

Each hit is a candidate, not a verdict: open the file and confirm.

### Review checklist

- [ ] **Methods**: GET is safe with no side effects; PUT and DELETE are idempotent; POST creates (201 + `Location`) or performs an action; no GET that changes state.
- [ ] **URLs**: plural nouns, hierarchy for ownership, consistent casing, version as the ADR requires.
- [ ] **Requests**: request DTOs separate from domain and persistence types; validation for every field; size limits.
- [ ] **Responses**: response DTOs; one consistent shape for single items, collections (paginated) and counts.
- [ ] **Status codes**: errors never return 2xx; 4xx for client faults and 5xx only for server faults; 401 vs 403 vs 404 used correctly.
- [ ] **Errors**: one problem format; machine-readable type or code; no internals leaked.
- [ ] **Compatibility**: no breaking change inside an existing version; deprecated items carry the headers and contract markers above.
- [ ] **Contract sync**: every endpoint in the code is in the contract and vice versa, with the same statuses, schemas and constraints.
- [ ] **Tests**: each changed endpoint has tests for the success, validation, not-found, authorization and conflict paths, naming the AC ids they prove.
