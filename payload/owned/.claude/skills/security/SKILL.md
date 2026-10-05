---
name: security
description: Threat-oriented secure-coding rules for implementing and judging any change - input validation, injection, authentication and authorization, secrets, sensitive data in logs, deserialization, SSRF, path traversal, security headers, dependencies, error leakage and rate limiting. Use for code at trust boundaries, auth, persistence, file or network access, configuration and reviews.
applies-to: any
last-verified: 2026-10-05
sources: rewritten from decebals/claude-code-java security-audit (0d98fe9) with its errors corrected; OWASP Top 10:2025 (top10.owasp.org, checked 2026-10-05); NIST SP 800-63B rev. 4 (Aug 2025)
---

# Security

Project rules come first: NEVER DO in `backbone/4-KNOWLEDGE.md`, the security NFRs in the spec, and the auth and security ADRs. The project's language skill gives the concrete APIs. For each rule ask: **what can an attacker control here, and what happens if they do?**

## Reference: OWASP Top 10:2025

A01 Broken Access Control; A02 Security Misconfiguration; A03 Software Supply Chain Failures; A04 Cryptographic Failures; A05 Injection; A06 Insecure Design; A07 Authentication Failures; A08 Software or Data Integrity Failures; A09 Security Logging and Alerting Failures; A10 Mishandling of Exceptional Conditions.

## Trust boundaries and input validation

- Untrusted: everything from HTTP requests (body, path, query, headers, cookies), messages, files, uploads, environment of other tenants, and responses from third-party services.
- Validate at the boundary with **allow-lists**: type, length, range, format, enum membership. Reject what doesn't match; don't try to clean it. Block-lists (`contains("<script")`) are always bypassable.
- Parse into typed value objects once at the boundary (`EmailAddress`, `OrderId`); domain code receives only validated types.
- Limit sizes: request body, collection lengths, string lengths, upload size, page size, nesting depth of JSON/XML.
- Canonicalise before validating (Unicode normalisation, URL decoding once) so checks and use see the same value.
- Encode output for its context (HTML, attribute, JavaScript, URL, CSV, shell) using the template engine's auto-escaping or an encoder library; never build markup by string concatenation with user data.

## Injection

- SQL and query languages: **parameterised queries / bind variables only**. Never concatenate or format input into SQL, JPQL, HQL, NoSQL filters, LDAP or XPath.
- Identifiers that cannot be bound (sort column, table name) are mapped from an allow-list: `SORT_COLUMNS = {"name": "c.name", "created": "c.created_at"}`.
- Template-string or interpolation SQL features (string templates, `${}` placeholders that splice raw text, "raw" or "unsafe" query helpers) are injection vectors unless the library documents that they bind values. Check before use.
- OS commands: avoid; if unavoidable, call the program with an argument array, never through a shell, with allow-listed arguments.
- Never evaluate input as code: no `eval`, dynamic expression languages or script engines on user data.
- Logs: strip or encode CR/LF in user-supplied values (log injection); prefer structured logging.

## Authentication

- Use the platform's or an established identity provider's authentication; never invent token formats or crypto.
- Validate tokens fully: signature with an expected algorithm (reject `none` and algorithm switching), issuer, audience, expiry and not-before, with a small clock skew.
- Passwords (NIST SP 800-63B rev. 4): minimum 15 characters when the password is the only factor, minimum 8 when used with MFA; allow at least 64 characters and all printable characters including spaces; check against a list of breached and common passwords; **no composition rules and no periodic forced rotation** (force a change only on evidence of compromise).
- Store passwords only with a slow, salted password hash (Argon2id, scrypt, bcrypt or PBKDF2 with a current work factor). Never plain, encrypted, or with a fast hash (MD5, SHA-x).
- Protect login, reset and MFA endpoints with rate limiting and lockout or back-off; return the same response for unknown user and wrong password.
- Sessions: regenerate the id at login, set cookies `Secure`, `HttpOnly`, `SameSite`; expire idle and absolute sessions; invalidate on logout server-side.
- Browser apps with cookie sessions need CSRF protection (synchroniser token or `SameSite` plus origin checks). Stateless APIs using bearer tokens in headers don't.

## Authorization

- **Deny by default**: every endpoint, use case and message handler states who may call it; anything unstated is refused.
- **Check ownership against the authenticated principal**, never against an id the client sends: `load order by id; require order.customerId == principal.customerId`. Missing check = IDOR.
- Enforce authorization in the **application layer** (use case), not only at the edge (gateway, controller annotations, UI hiding). Edge checks are a second layer, not the only one.
- Return 404 instead of 403 where revealing existence is itself a leak, if the API conventions allow.
- Mass assignment: map request DTOs explicitly; never bind input directly onto entities (a client must not set `role`, `ownerId`, `price`).
- Multi-tenant data: every query filters by the tenant from the principal; add a test that tenant A cannot read tenant B's record.

## Secrets and cryptography

- Never put secrets in code, tests, images, config files in the repo, URLs, logs or error messages. Example and test values are obviously fake.
- Load secrets from environment variables or a secret manager at runtime; keep `.env` and key files out of version control.
- Secrets are rotatable without a code change; on suspected exposure, rotate first, then clean history.
- Use TLS for all network traffic carrying credentials or personal data, including internal hops where the ADRs require it.
- Use vetted libraries and current algorithms (AES-GCM, ChaCha20-Poly1305, Ed25519/ECDSA, SHA-256+); a cryptographically secure random generator for tokens, ids and nonces; never a home-made scheme.

## Sensitive data and logging

- Never log passwords, tokens, API keys, session ids, full card numbers, secrets or personal data beyond what an ADR allows. Mask or omit; log ids instead of contents.
- Don't log whole request or response bodies by default.
- Do log security events: login success and failure, access denied, validation rejections at volume, privilege changes; with principal id, correlation id and outcome.
- Return only the fields the client needs; never serialise entities directly (password hashes and internal flags leak).

## Errors and exceptional conditions

- Error responses never contain stack traces, SQL, file paths, class names, internal hostnames or library versions. Log the detail with a correlation id; return a generic problem response with that id.
- Fail closed: an exception during an authorization or validation check results in denial, never in access.
- Handle every error path deliberately (timeouts, partial failures, resource exhaustion); release resources and don't leave half-applied state.

## Deserialization and parsing

- Never deserialize untrusted data with native object serialization (Java `ObjectInputStream`, Python `pickle`, .NET `BinaryFormatter`, PHP `unserialize`) or YAML loaders that construct arbitrary types.
- JSON: bind to explicit DTO types. **Never enable default or global polymorphic typing** (e.g. Jackson `activateDefaultTyping`, especially with a permissive validator: that is a known remote-code-execution configuration). If polymorphism is required, declare it per type with a logical type name and an **allow-list** of subtypes.
- XML: disable external entities and DTDs (XXE) and limit entity expansion.
- Limit input size and depth before parsing; reject unknown fields if the API conventions require strict input.

## SSRF and outbound requests

- Don't fetch URLs supplied by users. If the feature requires it: allow-list schemes (`https`) and hosts, resolve the host and reject private, loopback, link-local and metadata addresses (e.g. `169.254.169.254`), re-check after redirects or disable them, and set timeouts and response-size limits.
- Call third parties through a gateway port with fixed base URLs from configuration.

## Files and paths

- Never build a file path from input directly. Map ids to server-chosen names, or resolve the path, normalise it and verify it is still inside the allowed base directory.
- Archive extraction: validate every entry's resolved path (zip slip) and cap total size and entry count.
- Uploads: allow-list content types by inspecting content, cap size, store outside the web root with generated names, and serve with `Content-Disposition` and `X-Content-Type-Options: nosniff`.

## HTTP security headers (browser-facing responses)

| Header | Value |
|---|---|
| `Content-Security-Policy` | Restrictive policy, e.g. `default-src 'self'; frame-ancestors 'none'`; no `unsafe-inline` scripts |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (HTTPS only) |
| `X-Content-Type-Options` | `nosniff` |
| Clickjacking | CSP `frame-ancestors`; `X-Frame-Options: DENY` only for old browsers |
| `Referrer-Policy` | `strict-origin-when-cross-origin` or stricter |
| `X-XSS-Protection` | Omit, or `0`. The legacy filter is deprecated and can create vulnerabilities; rely on CSP |

CORS: allow-list origins explicitly; never reflect the `Origin` header or combine `*` with credentials.

## Supply chain and configuration

- Scan dependencies and container images for known vulnerabilities in CI and fail on the severity the project sets; pin versions with a lock file or dependency verification.
- Add a dependency only with a reason (and an ADR when the architecture rules say so); prefer maintained, widely used libraries.
- Production config: debug endpoints, stack traces, default credentials, admin consoles and sample apps are off; only required ports are open.

## Rate limiting and resource exhaustion

- Public and authentication endpoints have rate limits per client or principal, returning 429 with `Retry-After`.
- Every outbound call, query and lock has a timeout; pagination has a maximum page size; expensive operations are bounded or queued.
- Regular expressions on untrusted input avoid catastrophic backtracking (no nested quantifiers) or use a linear-time engine.

Read `checklist.md` when judging or reviewing a change for security.

## Linked skills

- `api-design`: status codes, problem responses and the per-endpoint authorization rule.
- `architecture`: where authorization and validation live (application layer, boundaries).
- `code-quality`: error handling and logging rules that these rules sharpen.
- `module-testing`: write negative tests for every authorization and validation rule (another user's record, oversized input).
- The project's language skill: the concrete validation, query-binding, hashing and header APIs.
