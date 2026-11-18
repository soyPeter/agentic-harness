# ADR-014: Keep human-action items visible in reviewer-first PR bodies

## Status
Proposed

## Date
2026-11-13

## Context
The [PR-body plan](../research/2026-11-pr-body-reviewer-opener-plan.md) proposes reducing receipt-heavy PR
descriptions without hiding the information a human needs for merge. Receipt length and reviewer fatigue are
hypotheses; the plan has not audited body assembly or real multi-task rendering.

Pedro's 10 November 2026 decision is audit-first: inspect 3–5 real PR bodies and stop if they are already short.
Any opener is optional and labelled, requires no mandatory human edit, and adds no model/effort metadata collection.

## Decision
If the audit demonstrates a presentation gap, derive a reviewer-first body from the existing receipt JSON:

1. An optional one-to-three-sentence opener states the change's intent. Label an agent draft honestly; never
   imply a person wrote or approved it. Preserve sections a person edited, or leave the body alone when unsure.
2. An always-visible human-action block lists Not verified, Approval needed, non-Accepted ADRs, open escalations,
   risk and its reason, and sandbox limits when isolation is absent or unrecorded. If empty, say
   “Nothing flagged by the receipt”; do not upgrade that to a safety or verification claim.
3. Fold the full, unchanged receipt in a details block. Its summary names task and harness version; identify the
   model only if already recorded. Do not start collecting model or effort metadata for this presentation change.
4. Preserve review follow-ups. WP1 determines their placement, multi-task layout and human-edit detection.

Receipt evidence and its limits remain authoritative for this view. Presentation does not add approval or merge
authority and does not change what a receipt proves.

## Alternatives considered
- Keep the current body: preferred if the audit finds no material readability gap.
- Fold the entire agent description: hides the very uncertainty and approval items the human must see.
- Require a human-written opener for every PR: adds a new ceremony that Pedro explicitly declined.

## Consequences
- WP1 audit precedes WP2 template, WP3 documentation and WP4 supervised trial. Fixtures must prove every relevant
  human-action item is outside the fold and the full receipt inside it matches receipt output unchanged.
- Human-edit preservation needs an explicit strategy before updates are enabled; guessing authorship is unsafe.
- Other forges must retain readable plain text where details folding is unsupported. Trial feedback decides
  whether the presentation helps, with no automatic adoption based on shorter bodies alone.
- Revert the template if the trial fails. No stored evidence, labels, approval rules or runtime state migrates.
