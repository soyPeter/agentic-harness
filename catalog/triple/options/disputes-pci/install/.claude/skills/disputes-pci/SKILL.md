---
name: disputes-pci
description: What the Disputes pilot parks (authentication, billing and payments, migrations, PCI evidence, secrets, infrastructure), who owns each surface, and how to escalate instead of editing. Use before any Disputes task and whenever a spec, plan or diff comes near those surfaces.
applies-to: Triple Disputes pilot repositories adopting the triple pack with the disputes-pci option
last-verified: 2026-11-05
sources: Triple adapter plan for agentic-harness (WP3, 5 Nov 2026); PCI DSS v4.0.1 requirements 3.3.1 (no sensitive authentication data after authorization) and 3.5 (PAN unreadable wherever stored)
---

# Disputes / PCI: parked surfaces

The accepted ADRs and `backbone/4-KNOWLEDGE.md` override this skill. The pilot covers **non-PCI surfaces only**: UI,
docs and skills. Everything below is parked. Agents don't edit it, and a spec that needs it is escalated before work
starts.

## What is parked, and who owns it

| Surface | Paths (examples) | Owner |
|---|---|---|
| Authentication, authorization, sessions | `auth/`, `iam/`, `sso/`, `oauth/`, `sessions/` | Security |
| Billing, payments, card data | `billing/`, `payments/`, `refunds/`, `ledger/`, `cards/`, `tokenization/`, `vault/` | Payments |
| Schema migrations | `migrations/`, `prisma/migrations/`, `db/migration/`, Flyway and Liquibase changelogs | Infra and DBA |
| PCI evidence and compliance | `pci*/`, `compliance/`, `audit-evidence/`, `attestations/` | Security and compliance |
| Secrets and key material | `.env*`, `secrets/`, `*.pem`, `*.key`, `*.p12`, keystores | Infra |
| Infrastructure | `terraform/`, `infra/`, `k8s/`, `helm/`, `deploy/` | Infra |

The guardrails refuse writes to these paths, from the file tools and from the shell. They also refuse running
migrations and writing a card verification value anywhere. They warn on anything that looks like a card number.

## Hard rules

1. **Don't route around a lock.** No generated file, symlink, script, renamed directory or "temporary" copy that ends
   up changing a parked surface. If the only way to finish is through a parked path, the task is out of scope.
2. **No real card data, ever.** No PAN, CVV/CVC, track data or PIN in code, tests, fixtures, logs or docs. Use
   tokens. In a test, use a brand's published test number and say so in a comment next to it.
3. **No sensitive data in logs.** Disputes code that logs a case logs its id, never the cardholder's name, PAN, email
   or address.
4. **Read-only is fine.** You may read parked code to understand an interface the change calls. Cite it in the spec;
   don't change it.

## When a task comes near a parked surface

- **Analyst**: if a requirement needs a parked surface, say so in the spec's Open questions and name the owner from the
  table. Don't write a requirement that changes it.
- **Griller**: a spec that changes a parked surface is a blocker. Ask for it to be cut or split, with the parked part
  going to its owner.
- **Implementer**: if the work turns out to need a parked path, stop. Report the path, why the change needs it and
  the owner. Don't look for another way in.
- **Judge and reviewers**: a diff that touches a parked path fails, whatever its tests say.

The escalation states the parked path, the owner, what the change needs from it and what can ship without it. In
supervised mode it goes to the user. In autonomous mode, which the pilot doesn't use, it goes through
`harness.py escalate`.

## Sandbox

The `harness-agent` devcontainer limits what an unattended agent can reach. It is **not** a PCI DSS control and nobody
has assessed it as one. Running in it doesn't make a task safe for PCI scope.

## Linked skills

- `security`: the checks for the code next to a parked surface (input handling, logging, secrets).
- `requirements-writing`: an escalated surface goes under Out of scope or Open questions, with its owner.
