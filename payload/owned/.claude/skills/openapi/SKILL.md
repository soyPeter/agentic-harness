---
name: openapi
description: Write, update or review OpenAPI 3.x contracts and keep them in sync with the API code. Use when adding or changing endpoints, request/response models or error formats.
applies-to: any
last-verified: 2026-10-04
---

# OpenAPI contracts

## Source of truth

The project states its approach in an ADR: **contract-first** (the spec file is written first and code or stubs are generated from it) or **code-first** (annotations generate the spec, which is committed and reviewed). Follow it. In both cases, the contract changes in the same commit as the behaviour.

## Writing the contract

- Use OpenAPI 3.0 or 3.1 as the project chooses. Fill `info.title`, `info.version` and `servers`.
- Each operation has:
  - a unique, stable `operationId` (`listCustomers`, `getCustomer`);
  - `summary` and `tags`;
  - every parameter with `required`, a `schema` and a `description`;
  - a `requestBody` with `required` and a content type;
  - **every** response it can return (success and the error codes from api-design), each with a schema.
- Reuse through `components`: `schemas`, `parameters`, `responses` (for example a shared `Problem` error response) and `securitySchemes`. Reference them with `$ref`; don't copy them.
- Schemas:
  - Give each `required` list explicitly.
  - Add `additionalProperties: false` on request bodies where the project wants strict input.
  - Use `format` (`date-time`, `uuid`, `email`), `enum`, `minLength`/`maxLength`, `minimum`/`maximum` and `pattern` to mirror the validation rules.
  - Mark `readOnly` fields that clients cannot send (`id`, `createdAt`).
  - Include examples for every request and response schema.
- Security: declare `securitySchemes` and apply `security` globally or per operation. Mark public endpoints explicitly with `security: []`.
- Pagination and errors follow one shared pattern, defined once in `components`.

## Keeping it honest

- Validate the file with the project's linter (for example Spectral or `openapi-generator validate`) if one is configured. Otherwise check that the YAML parses and every `$ref` resolves.
- Every implemented endpoint is in the contract, and every contract operation is implemented. Check both directions.
- Breaking changes (see api-design) require a version change and an ADR. Note them in the PR or commit body.

## Review checklist

- Do the status codes and schemas match what the code really returns, including errors?
- Do the validation constraints in the schema match the code's validation?
- Are the examples valid against their schemas?
- Are `operationId`s stable? Renaming one breaks generated clients.

## Linked skills

- `api-design`: the HTTP semantics, status codes, error format and compatibility rules the contract encodes.
- `security`: `securitySchemes`, per-operation security and input constraints.
- `module-testing`: contract tests that check the implementation against the file.
- `changelog`: release notes for contract changes.
