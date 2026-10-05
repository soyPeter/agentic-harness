# Security review checklist

Part of the `security` skill. Used by the judge and in reviews; each item references a section of `SKILL.md`. Review only the code the task changes, plus the paths it newly exposes. Report each failed item with file, line and the concrete attack, e.g. "customer B can read customer A's invoice via `GET /invoices/{id}`".

## How to review

1. List the trust boundaries the change touches: new or changed endpoints, message handlers, file or network access, queries, configuration.
2. For each boundary, walk the sections below.
3. Check that the spec's security NFRs and the security ADRs are met.
4. Check that tests exist for the negative paths (denied access, rejected input).

## Input and output

- [ ] Every external input is validated with allow-lists (type, length, range, format) before use.
- [ ] Sizes are limited: body, strings, collections, uploads, page size.
- [ ] Output is encoded for its context; no HTML or script built by concatenating user data.

## Injection

- [ ] All queries use bound parameters; no input concatenated or interpolated into SQL or other query languages.
- [ ] Non-bindable identifiers (sort fields, table names) come from an allow-list map.
- [ ] No shell invocation with input; no `eval` or dynamic expression evaluation of input.
- [ ] User values written to logs cannot inject line breaks.

## Authentication

- [ ] Tokens are validated for signature (fixed algorithm), issuer, audience and expiry.
- [ ] Password rules follow NIST SP 800-63B rev. 4 (length minimums, breached-password check, no composition rules, no forced periodic rotation).
- [ ] Passwords are stored with a slow salted hash; no fast hashes or encryption.
- [ ] Login and reset are rate-limited and don't reveal whether an account exists.
- [ ] Session cookies are `Secure`, `HttpOnly`, `SameSite`; CSRF protection where cookies authenticate.

## Authorization

- [ ] Every new endpoint or handler has an explicit rule; the default is deny.
- [ ] Ownership and tenant checks compare the resource with the authenticated principal, not with client-supplied ids.
- [ ] The check is in the application layer (use case), not only at the edge.
- [ ] Request DTOs are mapped explicitly; clients cannot set privileged fields.
- [ ] A test proves another principal or tenant is refused.

## Secrets and crypto

- [ ] No secrets in code, tests, config in the repo, images, logs or URLs.
- [ ] Secrets come from environment or a secret manager and can be rotated without a code change.
- [ ] Tokens and ids use a secure random generator; only vetted crypto libraries and current algorithms.

## Data exposure and logging

- [ ] Logs contain no passwords, tokens, keys, session ids or personal data beyond what is allowed.
- [ ] Responses expose only intended fields; no entities serialised directly.
- [ ] Security events (auth failures, access denied) are logged with principal and correlation id.

## Errors

- [ ] Error responses contain no stack traces, SQL, paths, class names or versions.
- [ ] Failures in security checks deny access (fail closed).
- [ ] Timeouts and partial failures leave no half-applied state.

## Deserialization and parsing

- [ ] No native object deserialization of untrusted data; no unsafe YAML loading.
- [ ] No default or global polymorphic typing; any polymorphism uses an explicit allow-list of subtypes.
- [ ] XML parsers disable external entities and DTDs.

## Outbound requests, files and paths

- [ ] No user-controlled URLs fetched, or host allow-list plus private-address and metadata-endpoint blocking, with timeouts and size limits.
- [ ] No file paths built from input without normalising and checking the base directory; archive entries checked.
- [ ] Uploads are type-checked by content, size-capped and stored with generated names outside the web root.

## Headers and configuration

- [ ] CSP (with `frame-ancestors`), HSTS, `X-Content-Type-Options: nosniff` and a referrer policy on browser-facing responses.
- [ ] `X-XSS-Protection` is absent or `0`.
- [ ] CORS allows only listed origins; no reflected origin with credentials.
- [ ] Debug features, default credentials and admin consoles are disabled in production configuration.

## Dependencies and resources

- [ ] New dependencies are justified, pinned and free of known high-severity vulnerabilities per the CI scan.
- [ ] Public and auth endpoints are rate-limited (429 with `Retry-After`).
- [ ] Outbound calls and queries have timeouts; regexes on input cannot backtrack catastrophically.

## Verdict guidance

- A failed item that violates a NEVER DO rule, a security ADR, a security NFR or an acceptance criterion fails the judge.
- Other failed items are reported as findings with a severity (High: exploitable now; Medium: exploitable with another weakness; Low: hardening).
- Findings outside the task's scope are recorded in `backbone/6-MEMORY.md` or proposed as a new task, not fixed in this task.
