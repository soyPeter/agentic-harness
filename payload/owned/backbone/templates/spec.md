# Spec <task-id>: <title>

Task: <task-id>
PRD: <the section of backbone/1-PRD.md this serves, or "none">
Change-Class: <docs | refactor | feature | schema>
<!-- Default if omitted: feature (conservative). See docs/adr/ADR-002-change-class-ladder.md in the
     harness repo (or the project note that links it). schema = migrations / auth / secrets / payments /
     deploy-infra. -->
Parent-CHNG: <vault or ticket id, or "none">
Parent-RFC: <link or id, or "none">
Parent-ADR: <project ADR ids that triggered this task, or "none">
<!-- Parent-* are optional process links. The vault/CHNG system of record stays outside the harness;
     do not invent a CHNG folder here. -->

## Context
<Why this is needed. The current behaviour, and who is affected.>

## Requirements
<!-- One behaviour per requirement, written as "The system shall ...". Ids are REQ-<task-id>-<n>.
     With HARNESS_REQ_STYLE="ears", use an EARS pattern (requirements-writing skill, ears.md):
     "When <trigger>, the <system> shall ...", "While <state>, ...", "If <condition>, then the <system> shall ...",
     "Where <feature>, ...". EARS is optional unless the project set HARNESS_REQ_STYLE=ears. -->
- REQ-<task-id>-1: The system shall <behaviour>.

## Acceptance criteria
<!-- Given/When/Then, observable and testable. Each one names the requirement(s) it proves.
     Every test that proves a criterion mentions its id, for example in the test name or a comment. -->
- AC-<task-id>-1 (REQ-<task-id>-1): Given <state>, when <action>, then <observable result>.

## Non-functional requirements
<!-- With HARNESS_REQ_STYLE="ears", an NFR a criterion proves gets an id: - NFR-<task-id>-1: ... -->
- <performance, security, availability or compatibility constraints, or "none">

## Architecture
ADRs: <ADR-002, ADR-005: every ADR that governs this work; the architect adds new ones when needed>
Tech requirements:
- <constraints the implementation must follow: layers, libraries, patterns, data, API contracts>

## Skills
<!-- Skills the implementation needs beyond those routed by path (.claude/skills/<name>). -->
- <skill-name>: <which part of the work needs it>

## Out of scope
- <what this task deliberately does not do>

## Assumptions
<!-- How questions were settled without the user, each with its source (a backbone/ file, an ADR, the PRD).
     A question marked apply records the griller's recommendation it applied (source: the griller's
     recommendation, grill round N). In autonomous mode, every question the griller raised must end up here
     or be escalated. -->
- none

## Open questions
<!-- Must be "- none" before the griller can pass the spec. -->
- none

## Approval
<!-- The user approves by adding a line "Approved-by: <name> (<date>)" below. Agents cannot.
     feature and schema always need a human Approved-by (no policy approve). docs/refactor may use
     policy:low-risk only when Change-Class and risk_reasons allow it (ADR-002). -->
