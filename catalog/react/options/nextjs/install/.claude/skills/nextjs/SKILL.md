---
name: nextjs
description: Write or review Next.js App Router code - server and client components and the boundary between them, server actions as public POST endpoints (auth and tenant from the session, input parsed by a schema), route handlers, middleware, caching and revalidation, environment variables (no secrets in NEXT_PUBLIC_), metadata and error/loading boundaries. Use before editing anything under app/, server actions, route handlers, middleware or next.config.
applies-to: Next.js 15+ App Router with React 19 and TypeScript
last-verified: 2026-11-05
sources: Next.js documentation (App Router, server and client components, server actions security, caching, environment variables); written for the Triple Disputes pilot (multi-tenant, server actions with org scoping)
---

# Next.js (App Router)

The accepted ADRs, `backbone/4-KNOWLEDGE.md` and the project's own lint rules override this skill. Parked surfaces
(authentication, payments, migrations: see `disputes-pci` when the project adopted it) stay parked here too.

## Hard rules (a review fails on any of these)

1. **Every export of a `"use server"` file is a public POST endpoint.** Anyone can call it with any arguments. Each one:
   - authenticates from the session, never from an argument;
   - derives the tenant (organisation) from the session through the project's helper, never from a caller-supplied
     id;
   - parses its input with a schema before use;
   - checks the caller may act on the record it names;
   - returns only what the caller may see.
   An exported action nothing imports is still an open endpoint: delete it.
2. **Secrets stay on the server.** `NEXT_PUBLIC_` variables are inlined into the browser bundle; the guardrails refuse
   secret-looking names there. Server-only modules import `server-only` so a client import fails the build.
3. **Server components by default.** Add `"use client"` only to the leaf that needs state, effects or browser APIs.
   Never pass secrets, full database rows or functions (other than server actions) from server to client components:
   pass the fields the UI shows.
4. **Route handlers and middleware** validate input, authenticate and authorise like server actions, and set explicit
   status codes and cache headers.

## Data and caching

- Fetch in server components or through the project's data layer, close to where data is used. Don't fetch in a
  client effect what a server component can load.
- Know what is cached: mark per-user or per-tenant data dynamic, and never cache a response that depends on the
  session under a shared key. After a mutation, revalidate the paths or tags that show the changed data.
- Database access stays in the server data layer the project defines; components don't import the database client.

## Routes and UI

- Each route segment that loads data has `loading` and `error` boundaries where the spec needs them, and `not-found`
  for missing records. Error boundaries show a safe message, never the raw error.
- Use the framework's `Link`, `Image` and metadata APIs. Redirect with the framework's helpers, not by writing
  `window.location` in server code.
- Keep request-pipeline code (middleware or proxy, instrumentation, `next.config`) small and reviewed: it runs on every
  request.

## Review checklist

- [ ] Each new or changed server action: session auth, tenant from the session, schema-parsed input, record-level
      authorisation, minimal return.
- [ ] No secret in `NEXT_PUBLIC_`, no server-only module reachable from a client component.
- [ ] `"use client"` only where needed; no rows or secrets passed to the client.
- [ ] Caching and revalidation match who may see the data.

## Linked skills

- `react`: component, hook and accessibility rules.
- `typescript`: types and schema parsing at boundaries.
- `security`: authentication, authorisation, injection and data exposure.
