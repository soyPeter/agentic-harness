---
name: react
description: Write or review React components and hooks in TypeScript - component boundaries and props, the rules of hooks, state placement, effects only for synchronising with outside systems, keys, accessibility (roles, labels, focus, contrast), safe rendering of user content, and component tests that query as a user would. Use before editing any .tsx or .jsx file or a custom hook.
applies-to: React 18 and 19 with TypeScript
last-verified: 2026-11-05
sources: react.dev (rules of hooks, "You might not need an effect", keys, thinking in React); WAI-ARIA authoring practices; Testing Library guiding principles; written for the Triple Disputes pilot
---

# React

The accepted ADRs, `backbone/7-CONVENTIONS.md` and the project's design system override this skill. Use the project's
existing components (its UI kit, icons, formatting helpers) before writing new ones.

## Hard rules (a review fails on any of these)

1. **Rules of hooks.** Hooks run at the top level of components and custom hooks, never in conditions, loops or
   callbacks. Custom hooks are named `useX`.
2. **No unescaped HTML.** `dangerouslySetInnerHTML` is refused by the guardrails. Render elements, or Markdown through
   the project's sanitizing renderer.
3. **Stable keys.** List items get a stable id as `key`, never the array index for lists that reorder, filter or grow.
4. **Accessible by default.** Interactive elements are real controls (`button`, `a href`, `input` with a `label`), not
   `div onClick`. Every image has `alt` (empty for decoration). Icons-only buttons have an accessible name. Focus is
   visible and moves deliberately in dialogs. Colour is never the only signal; meet the project's contrast rules.
5. **Props are typed and minimal.** Export the props type; pass data, not whole objects a component half uses. No
   prop drilling past two levels: lift state or use the project's context or query cache.

## State and effects

- Derive what you can during render; don't store derived values in state.
- Keep state as close as possible to where it is used; lift it only when siblings share it.
- Effects synchronise with something outside React (a subscription, the DOM, a timer). Don't use an effect to compute
  state from props, to handle an event, or to fetch data the framework or query library can fetch. Every effect that
  subscribes cleans up.
- Server state goes through the project's data layer (server components, or a query cache such as TanStack Query),
  with loading, empty and error states the spec names.
- Forms: controlled inputs or the framework's form actions; validate with the same schema the server uses, and show
  the server's errors next to their fields.

## Components

- One component per file for anything exported; small private subcomponents may live alongside.
- Text the user sees goes through the project's i18n helpers when it has them; numbers, dates and money through its
  formatting helpers.
- Don't optimise blind: `memo`, `useMemo` and `useCallback` only with a measured reason or a referential-identity need.

## Testing components

- Render the component as used, then query by role, label or visible text (`getByRole("button", { name: "Save" })`),
  never by CSS selector or test id unless nothing user-facing exists.
- Interact the way a user does, then assert what the user sees. Test the loading, empty and error states.
- Name each test by the AC id it proves (`typescript-test` skill).

## Linked skills

- `typescript`: types, narrowing and boundaries.
- `typescript-test`: the runner, naming and mocking rules for component tests.
- `security`: XSS and handling user-supplied content.
