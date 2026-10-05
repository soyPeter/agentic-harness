# Spec <task-id>: <title>

Task: <task-id>
PRD: <the section of backbone/1-PRD.md this serves, or "none">

## Context
<Why this is needed. The current behaviour, and who is affected.>

## Requirements
<!-- One behaviour per requirement, written as "The system shall ...". Ids are REQ-<task-id>-<n>. -->
- REQ-<task-id>-1: The system shall <behaviour>.

## Acceptance criteria
<!-- Given/When/Then, observable and testable. Each one names the requirement(s) it proves.
     Every test that proves a criterion mentions its id, for example in the test name or a comment. -->
- AC-<task-id>-1 (REQ-<task-id>-1): Given <state>, when <action>, then <observable result>.

## Non-functional requirements
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

## Open questions
<!-- Must be "- none" before the griller can pass the spec. -->
- none

## Approval
<!-- The user approves by adding a line "Approved-by: <name> (<date>)" below. Agents cannot. -->
