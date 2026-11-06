---
name: typescript
description: Write or review TypeScript on Node.js - strict compiler settings, precise types over any and casts, narrowing unknown input with a schema at every trust boundary, discriminated unions and exhaustive switches, async error handling, module layout and exports. Use before editing any .ts or .tsx file.
applies-to: TypeScript 5.x with "strict": true, Node.js 20+
last-verified: 2026-11-05
sources: TypeScript handbook (narrowing, unions, satisfies, unknown); typescript-eslint strict rules; written for the Triple Disputes pilot (Next.js, Prisma, Zod) and kept stack-neutral beyond TypeScript
---

# TypeScript

The accepted ADRs, `backbone/4-KNOWLEDGE.md` and `backbone/7-CONVENTIONS.md` override this skill. Follow the project's
lint and format configuration (ESLint, Prettier); don't restyle code you don't otherwise change.

## Hard rules (a review fails on any of these)

1. **The compiler is strict, and stays so.** Never loosen `tsconfig.json` (`strict`, `noUncheckedIndexedAccess`,
   `exactOptionalPropertyTypes`) to make code compile. The build command runs `tsc --noEmit`; it must pass.
2. **No `any`.** Use `unknown` and narrow it, or write the precise type. `as` is for facts the compiler can't see
   (a DOM element's subtype after a check), never to silence an error. `as unknown as T` is a defect.
3. **No `@ts-ignore` or `@ts-nocheck`.** When a suppression is unavoidable (a broken third-party type), use
   `// @ts-expect-error <why, with a link>`: it fails once the error is gone.
4. **Validate at trust boundaries.** Request bodies, query strings, form data, webhook payloads, environment variables,
   JSON from files, queues and third-party APIs are `unknown` until a schema (the project's choice, often Zod) parses
   them. Derive the type from the schema (`z.infer<typeof Schema>`), so the two can't drift.
5. **Non-null assertions (`!`) only on values just checked.** For lookups (`map.get`, `array[i]`, `find`) handle the
   `undefined` case: return early, throw a named error, or provide a default the requirement states.
6. **Every promise is awaited, returned or explicitly handled.** No floating promises; `void promise` only for
   fire-and-forget work whose failure is logged inside it. Don't mix `.then` chains and `await` in one function.
7. **Errors are values with meaning.** Throw `Error` subclasses (or return a result union) that name the failure;
   never throw strings or plain objects. Catch `unknown`, narrow it (`err instanceof X`), and rethrow what you can't
   handle. Don't swallow errors in empty `catch` blocks.

## Types that carry the design

- **Discriminated unions** for states (`{ status: "open"; ... } | { status: "closed"; closedAt: Date }`), with an
  exhaustive `switch` ending in `const never: never = value` so a new state fails to compile.
- **`as const satisfies Type`** for lookup tables and configuration: it checks the shape and keeps the literal keys,
  where a `: Record<K, V>` annotation would widen them and hide missing entries.
- **Branded or nominal ids** (`type CaseId = string & { readonly brand: "CaseId" }`) when two kinds of string id can be
  confused at a call site.
- **`readonly`** arrays and properties for data a function must not change. Prefer returning new values over mutating
  arguments.
- **Optional is not nullable.** `x?: T` means "may be absent"; `x: T | null` means "present, explicitly empty". Pick
  the one the data model means, and don't accept both.
- Keep types next to the code that owns them. Export types from the module's public entry, not from deep paths.

## Functions and modules

- Small functions with explicit parameter and return types on exported functions. Let inference type locals.
- Pass an options object once there are more than three parameters, or two of the same type.
- ES modules only (`import`/`export`). No side effects at import time beyond defining things: no network calls, no
  reading the environment outside the module that parses it once.
- One module, one responsibility; no barrel files that re-export a whole folder in hot paths (they defeat tree shaking
  and create cycles). Fix import cycles; don't work around them with dynamic imports.
- Dates: store and pass `Date` or ISO-8601 strings with a time zone; format only at the edge, through the project's
  formatting helpers. Money: integer minor units or the project's decimal type, never floating-point arithmetic.

## Async and resources

- Run independent work concurrently (`Promise.all`), but bound fan-out over unbounded inputs.
- Use `AbortSignal` and timeouts for outbound calls; a call without a timeout can hang a request forever.
- Close what you open (`try/finally`, `using` where supported): file handles, DB transactions, locks.

## Logging and secrets

- Log through the project's logger with structured fields. Never log secrets, tokens, credentials or personal data.
- Read configuration once, through a validated schema. Never hard-code secrets or fall back to a default secret.

## Review checklist

- [ ] `tsc --noEmit` passes; no new `any`, casts or suppressions without a reason.
- [ ] Every external input is parsed by a schema before use.
- [ ] Unions are handled exhaustively; `undefined` from lookups is handled.
- [ ] No floating promises; errors are typed, narrowed and never swallowed.
- [ ] Public functions have explicit types; modules have no import-time side effects.

## Linked skills

- `typescript-test`: how the tests for this code are written and named.
- `code-quality`: naming, function size and duplication, for any language.
- `security`: input validation, injection and secrets at the boundaries this skill names.
