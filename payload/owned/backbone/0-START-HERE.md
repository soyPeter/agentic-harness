# 0. Start Here

`backbone/` is the project's shared memory for people and AI agents. Agents follow `AGENTS.md`; people can read this page first.

## Map

| File | Owner | Purpose | Read |
|---|---|---|---|
| `1-PRD.md` | project | What we build, for whom, what good looks like | Onboarding, defining tasks |
| `2-PLANNING.md` | project | Structure, modules, main flows | Onboarding |
| `3-TASKS.md` | project | Milestones and the task index; at most one `[WIP]` | Every task |
| `4-KNOWLEDGE.md` | project | Stack, design rules, NEVER DO list, commands | Every session |
| `5-DECISIONS.md` | project | Index of the ADRs | Before choosing a pattern |
| `adr/` | project | Architecture Decision Records, one per file | When specs reference them |
| `specs/` | project | One spec per task: requirements, acceptance criteria, architecture, skills, approval | Every task |
| `6-MEMORY.md` | project | Traps, lessons, open questions | When stuck or debugging |
| `7-CONVENTIONS.md` | project | Code, test and commit conventions, extra DoD items | Every session |
| `8-WORKFLOW.md` | harness | The pipeline loop and Definition of Done | Every session |
| `9-AGENT-SKILLS.md` | project | Project skills and when to use them | When choosing skills |
| `SKILLS.md` | harness | Skill format and routing | Writing skills or routes |
| `HOOKS.md` | harness | Every hook and gate, and how to tune them | When a hook fires |
| `templates/` | harness | Spec and ADR templates | Writing specs and ADRs |
| `harness.conf` | project | Commands, test paths, gate switches | Setup |
| `guardrails.conf` | project | Project rules that hooks enforce | Setup, new NEVER DO |
| `routing.conf` | project | Which skills each path requires | Setup, new layers |
| `.verdicts/` | hooks | Griller and judge verdicts per task (audit trail) | When a gate refuses |
| `.harness-lock.json` | harness | Installed version and file hashes; do not edit | Never |

"harness" files are replaced by harness updates. "project" files belong to this project; the harness creates them once and never touches them again. Agents live in `../.claude/agents/` and skills in `../.claude/skills/`.

## Dependency order

```
1-PRD (what, optional) -> specs/<id> (requirements + acceptance criteria)
4-KNOWLEDGE + adr/ (rules and decisions) -> specs/<id> Architecture -> code and tests
8-WORKFLOW drives the pipeline; 3-TASKS tracks it; .verdicts/ proves each gate was passed.
```

## Health check

Run `scripts/harness/doctor.sh` to check hooks, agents, routes and configuration. Run `python3 scripts/harness/lib/harness.py spec-check <task-id>` to see a spec's readiness.
