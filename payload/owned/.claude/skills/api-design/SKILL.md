---
name: api-design
description: Design, implement or review HTTP APIs - resources, methods, status codes, errors, validation, pagination, versioning and compatibility. Use for controllers, resources, handlers, routes and any outer API layer code.
applies-to: any
last-verified: 2026-10-04
---

# HTTP API design

Follow the project's conventions in `backbone/7-CONVENTIONS.md` and the API ADRs first. Where they say nothing, use these defaults.

## Resources and methods

- Use nouns and plurals for collections: `/customers`, `/customers/{id}`, `/customers/{id}/orders`. No verbs in paths, except for real actions (`POST /orders/{id}/cancel`).
- Use methods for their semantics:
  - GET reads and is safe.
  - POST creates or performs an action.
  - PUT replaces and is idempotent.
  - PATCH partially updates.
  - DELETE removes and is idempotent.
- Make retries safe: PUT and DELETE are idempotent. For POST that creates, support an idempotency key when clients may retry.

## Status codes

| Situation | Code |
|---|---|
| Read OK | 200 |
| Created | 201, with a `Location` header and the representation |
| Accepted for async processing | 202 |
| Success, no body | 204 |
| Malformed or invalid input | 400 (or 422 if the project uses it for validation) |
| Not authenticated | 401 |
| Authenticated but not allowed | 403 |
| Not found | 404 |
| Conflict, duplicate or version mismatch | 409 (412 with `If-Match`) |
| Server fault | 500; never for client mistakes |

## Errors

- Use one error format everywhere, preferably RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`, `instance`, plus field errors).
- Never leak stack traces, SQL or internal ids in error bodies. Log them with a correlation id instead.
- Validation errors list every invalid field, not only the first.

## Input and output

- Validate at the boundary: types, ranges, lengths, formats and required fields. Reject unknown enum values.
- Keep request and response DTOs separate from domain and persistence models.
- Collections are paginated by default (cursor or page/size), with a maximum page size and a documented stable sort order.
- Timestamps are ISO-8601 with an offset (UTC). Money is not a binary float.

## Compatibility and versioning

- Additive changes (new optional fields, new endpoints) are compatible.
- Removing or renaming fields, changing types or semantics, or adding required input is breaking. It needs a new version (`/v2`, or a media type) and an ADR.
- The contract (OpenAPI) is updated in the same change as the code (openapi skill).
- Deprecate before removing: `Deprecation` (RFC 9745) and `Sunset` (RFC 8594) headers, docs and a timeline.

Read `compatibility.md` when changing or deprecating an existing endpoint, or reviewing an API contract.

## Security

- Every endpoint states its authorization rule. Deny by default.
- Never trust ids from the client for ownership checks. Check them against the authenticated principal.
- Rate-limit and size-limit inputs on public endpoints.

## Tests

- For each endpoint, test the happy path, validation failures, not found, the authorization failure, and any conflict. Assert the status, the body shape and the headers.
- Test names or comments mention the acceptance criterion ids they prove.

## Linked skills

- `openapi`: keep the contract in sync with every endpoint change.
- `security`: authentication, authorization, input limits and error leakage for endpoints.
- `module-testing`: endpoint tests and AC traceability.
- `architecture`: keep the API layer thin; logic belongs in the application and domain layers.
- `adr-writing`: record API style, versioning and error-format decisions, and every breaking change.
- `changelog`: describe API and breaking changes for a release.
