# Changelog

## 0.14.0 (2026-10-17)

**Enforce it everywhere.** The harness now makes sure every project is enrolled and every agent follows the gates:
- `enroll.sh`: installs or updates the harness and runs the doctor; registers the project in Orca; with `--automation <schedule>`, creates one Orca automation per checkout whose precheck starts `harness.py orca-nightly` in its own terminal and whose agent reports `harness.py orca-digest`; with `--protect`, requires CI checks on the default branch while keeping existing protection.
- **Machine guard**: `machine.sh install` adds user-level hooks for Claude Code and Codex that warn or block edits in unenrolled repositories; `machine.sh managed` writes admin files to a directory for review and installation with sudo.
- **Orca skill**: `orca/skills/agentic-harness/SKILL.md` provides instructions for coordinators; it requires one coordinator per repository (via a lock) and forbids agents from starting `harness.py orca` or `orca-nightly`.
- **Harness commands**: adds `orca-nightly` and `orca-digest`.
- A Codex review found 19 issues (14 major, 5 minor), all fixed, with tests for each.
- The test suite covers the enrollment flow, machine guard behavior, and skill command validity.

## 0.13.3 (2026-10-17)
...
