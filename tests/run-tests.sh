#!/usr/bin/env bash
# Self-test: installs the harness into throwaway repositories and exercises the
# installer, every Claude Code hook, the git hooks and the update path.
# Usage: tests/run-tests.sh
set -u

HARNESS="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/harness-test.XXXXXX")"
WORK="$(cd "$WORK" && pwd -P)"
trap 'rm -rf "$WORK"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com \
       GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); printf '  ok    %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/        /'; }
section() { printf '\n%s\n' "$1"; }

# expect <exit code> <name> <command...>
expect() {
  local want=$1 name=$2 out got
  shift 2
  out=$("$@" 2>&1); got=$?
  if [ "$got" -eq "$want" ]; then ok "$name"; else bad "$name (exit $got, expected $want)" "$out"; fi
}
# contains <name> <needle> <haystack>
contains() { case "$3" in *"$2"*) ok "$1" ;; *) bad "$1 (missing: $2)" "$3" ;; esac; }
lacks()    { case "$3" in *"$2"*) bad "$1 (unexpected: $2)" "$3" ;; *) ok "$1" ;; esac; }

hook() {  # hook <project> <event> <json>
  printf '%s' "$3" | CLAUDE_PROJECT_DIR="$1" python3 "$1/scripts/harness/lib/harness.py" hook "$2"
}
bash_json() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "$1"; }
write_json() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Write","tool_input":{"file_path":sys.argv[1],"content":sys.argv[2]}}))' "$1" "$2"; }
edit_json() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Edit","tool_input":{"file_path":sys.argv[1],"old_string":sys.argv[2],"new_string":sys.argv[3]}}))' "$1" "$2" "$3"; }
new_repo() { mkdir -p "$1" && git -C "$1" init -q; }
guard() {  # guard <project> <agent> <json>: the write-scope hook scoped to one agent
  printf '%s' "$3" | CLAUDE_PROJECT_DIR="$1" python3 "$1/scripts/harness/lib/harness.py" hook agent-guard "$2"
}
# session-aware tool inputs: swrite <session> <path> <content>, sread <session> <path>, sskill <session> <name>
swrite() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[1],"tool_name":"Write","tool_input":{"file_path":sys.argv[2],"content":sys.argv[3]}}))' "$1" "$2" "$3"; }
sread()  { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[1],"tool_name":"Read","tool_input":{"file_path":sys.argv[2]}}))' "$1" "$2"; }
sskill() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[1],"tool_name":"Skill","tool_input":{"skill":sys.argv[2]}}))' "$1" "$2"; }
# stop_json <agent> <final message> [stop_hook_active]: SubagentStop input
stop_json() { python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"SubagentStop","agent_type":sys.argv[1],"stop_hook_active":sys.argv[3]=="true","last_assistant_message":sys.argv[2]}))' "$1" "$2" "${3:-false}"; }
# greport <verdict> <blocker|major|minor|none>: griller final message for task 2.1
greport() {
  python3 -c 'import json,sys
v, sev = sys.argv[1:3]
qs = [] if sev == "none" else [{"severity": sev, "about": "AC-2.1-1", "question": "Is the search accent-insensitive?", "why": "unstated"}]
print("Grilled.\n\n```json\n" + json.dumps({"verdict": v, "task": "2.1", "questions": qs, "summary": "s"}, indent=2) + "\n```")' "$1" "$2"
}
# jreport <verdict> <tests result> <AC ids...>: judge final message for task 2.1, each listed AC met
jreport() {
  python3 -c 'import json,sys
v, tests, acs = sys.argv[1], sys.argv[2], sys.argv[3:]
crit = [{"id": a, "met": True, "evidence": "src/api/search_controller.py:1", "tests": ["test_" + a]} for a in acs]
body = {"verdict": v, "task": "2.1", "criteria": crit, "findings": [], "tests": {"command": "pytest", "result": tests}, "summary": "s"}
print("Judged.\n\n```json\n" + json.dumps(body, indent=2) + "\n```")' "$@"
}

P="$WORK/demo"

section "install"
new_repo "$P"
expect 0 "bootstrap into an empty repo" "$HARNESS/bootstrap.sh" "$P" --name demo
for f in AGENTS.md CLAUDE.md backbone/1-PRD.md backbone/3-TASKS.md backbone/8-WORKFLOW.md \
         backbone/HOOKS.md backbone/harness.conf backbone/guardrails.conf backbone/.harness-lock.json \
         .claude/settings.json scripts/harness/lib/harness.py; do
  [ -f "$P/$f" ] && ok "created $f" || bad "created $f"
done
[ -x "$P/scripts/harness/git-hooks/pre-commit" ] && ok "git hooks are executable" || bad "git hooks are executable"
contains "core.hooksPath set" "scripts/harness/git-hooks" "$(git -C "$P" config core.hooksPath)"
contains "project name rendered" "Product Requirements: demo" "$(cat "$P/backbone/1-PRD.md")"
lacks "no unrendered template keys" "{{PROJECT_NAME}}" "$(cat "$P"/backbone/*.md "$P/CLAUDE.md")"
settings=$(cat "$P/.claude/settings.json")
for event in SessionStart PreToolUse PostToolUse Stop; do contains "settings has $event" "\"$event\"" "$settings"; done
expect 2 "second bootstrap is refused" "$HARNESS/bootstrap.sh" "$P"
expect 2 "update without a lock is refused" "$HARNESS/update.sh" "$WORK"
mkdir -p "$WORK/plain"
expect 2 "non-git target is refused" "$HARNESS/bootstrap.sh" "$WORK/plain"
expect 0 "--git-init initialises it" "$HARNESS/bootstrap.sh" "$WORK/plain" --git-init
expect 0 "doctor passes on a fresh install" "$P/scripts/harness/doctor.sh"

section "session start and stop on a fresh project"
out=$(hook "$P" session-start '{}')
contains "reports SETUP INCOMPLETE" "SETUP INCOMPLETE" "$out"
lacks "no WIP on the fresh task template" "Task in progress" "$out"
lacks "no harness errors" "Harness problems" "$out"
expect 0 "stop is silent without WIP" test -z "$(hook "$P" stop '{}')"

section "pre-tool-use: shell commands"
for cmd in "git reset --hard HEAD~1" "git clean -fd" "git push --force origin main" "git push -f" \
           "git commit --no-verify -m x" "rm -rf /" "rm -rf ~" "rm -rf ." "rm -fr *" "rm -r -f ./" \
           "psql -c 'DROP TABLE users'" "echo 'truncate table t' | psql"; do
  expect 2 "blocks: $cmd" hook "$P" pre-tool-use "$(bash_json "$cmd")"
done
for cmd in "git status" "rm -rf ./build" "rm -rf /tmp/cache" "git push --force-with-lease" \
           "git reset --soft HEAD~1" "rm -f notes.txt" "grep -r 'drop' src"; do
  expect 0 "allows: $cmd" hook "$P" pre-tool-use "$(bash_json "$cmd")"
done
out=$(cd / && hook "$P" pre-tool-use "$(bash_json 'git reset --hard')" 2>/dev/null; echo "exit=$?")
contains "works from another working directory" "exit=2" "$out"

section "pre-tool-use: file rules"
hook "$P" post-tool-use "$(sskill session code-quality)"
KEY_HEADER="-----BEGIN RSA PRIVATE KEY-----"
expect 2 "blocks a private key" hook "$P" pre-tool-use "$(write_json "$P/id_rsa" "$KEY_HEADER")"
expect 2 "blocks an AWS key id" hook "$P" pre-tool-use "$(write_json "$P/app.py" "key = 'AKIAIOSFODNN7EXAMPLE'")"
expect 0 "allows ordinary content" hook "$P" pre-tool-use "$(write_json "$P/app.py" "print('hi')")"
printf '%s\n' 'block | \.py$ | ^import pickle$ | Never use pickle; use json.' \
              'warn | \.py$ | print\( | Use logging instead of print.' >> "$P/backbone/guardrails.conf"
expect 2 "project block rule applies" hook "$P" pre-tool-use "$(write_json "$P/a.py" "import pickle")"
expect 0 "project rule ignores other paths" hook "$P" pre-tool-use "$(write_json "$P/a.txt" "import pickle")"
out=$(hook "$P" post-tool-use "$(write_json "$P/a.py" "print(1)")")
contains "warn rule reported after the edit" "Use logging instead of print" "$out"
contains "warn uses additionalContext" '"additionalContext"' "$out"
out=$(hook "$P" post-tool-use "$(edit_json "$P/AGENTS.md" "x" "y")")
contains "edit of a harness-owned file is flagged" "harness-owned" "$out"
echo 'block | [unclosed | x | broken' >> "$P/backbone/guardrails.conf"
expect 1 "doctor reports an invalid rule" "$P/scripts/harness/doctor.sh"
sed -i.bak '/unclosed/d' "$P/backbone/guardrails.conf" && rm -f "$P/backbone/guardrails.conf.bak"

section "single WIP task"
T="$P/backbone/3-TASKS.md"
anchor="## Status markers"
HARNESS_SPEC_GATE=off expect 0 "first WIP task is allowed" hook "$P" pre-tool-use "$(edit_json "$T" "$anchor" "- [WIP] Task A
$anchor")"
python3 - "$T" <<'EOF'
import sys
p = sys.argv[1]; s = open(p).read()
open(p, "w").write(s.replace("## Status markers", "- [WIP] Task A\n\n## Status markers", 1))
EOF
expect 2 "second WIP task is refused" hook "$P" pre-tool-use "$(edit_json "$T" "$anchor" "- [WIP] Task B
$anchor")"
expect 2 "second WIP via Write is refused" hook "$P" pre-tool-use "$(write_json "$T" "- [WIP] Task A
- [WIP] Task B")"
expect 2 "finishing without a judge verdict is refused" hook "$P" pre-tool-use "$(edit_json "$T" "- [WIP] Task A" "- [x] Task A")"
HARNESS_SPEC_GATE=off HARNESS_ALLOW_PARALLEL_WIP=1 expect 0 "parallel WIP allowed when configured" hook "$P" pre-tool-use "$(edit_json "$T" "$anchor" "- [WIP] Task B
$anchor")"
out=$(hook "$P" session-start '{}')
contains "session start resumes the WIP task" "A (spec: backbone/specs/A.md)" "$out"

section "stop hook"
out=$(hook "$P" stop '{}')
contains "remind mode shows a systemMessage" '"systemMessage"' "$out"
out=$(HARNESS_STOP_MODE=block hook "$P" stop '{}')
contains "block mode blocks once" '"decision": "block"' "$out"
out=$(HARNESS_STOP_MODE=block hook "$P" stop '{"stop_hook_active": true}')
lacks "block mode lets the agent stop the second time" '"decision"' "$out"
expect 0 "off mode is silent" test -z "$(HARNESS_STOP_MODE=off hook "$P" stop '{}')"

section "agents and skills"
for a in analyst architect griller implementer judge scribe; do
  [ -f "$P/.claude/agents/$a.md" ] && ok "installed agent $a" || bad "installed agent $a"
done
for s in requirements-writing adr-writing architecture api-design openapi; do
  [ -f "$P/.claude/skills/$s/SKILL.md" ] && ok "installed skill $s" || bad "installed skill $s"
done
contains "griller declares its verdict recorder" "hook grill-stop" "$(cat "$P/.claude/agents/griller.md")"
contains "judge declares its verdict recorder" "hook judge-stop" "$(cat "$P/.claude/agents/judge.md")"
for a in analyst architect implementer scribe; do
  contains "$a declares its write scope" "hook agent-guard $a" "$(cat "$P/.claude/agents/$a.md")"
done

section "pipeline: define"
F="$WORK/flow"
new_repo "$F"
"$HARNESS/bootstrap.sh" "$F" --name flow >/dev/null
FT="$F/backbone/3-TASKS.md"
SPEC="$F/backbone/specs/2.1.md"
mkdir -p "$F/backbone/specs"
mkdir -p "$F/.claude/skills/python"
printf -- '---\nname: python\ndescription: Python rules\napplies-to: python>=3.11\nlast-verified: 2026-10-04\n---\n# Python\n' \
  > "$F/.claude/skills/python/SKILL.md"
printf '%s\n' '\.py$ | python | All Python code.' '(?i)(controller|/api/) | api-design | Outer API layer.' \
  >> "$F/backbone/routing.conf"
read -r -d '' SPEC_TEXT <<'EOF'
# Spec 2.1: Customer search

Task: 2.1
PRD: none

## Context
Support needs to find customers by name.

## Requirements
- REQ-2.1-1: The system shall return customers whose name contains the query, ignoring case.
- REQ-2.1-2: The system shall reject queries shorter than 2 characters.

## Acceptance criteria
- AC-2.1-1 (REQ-2.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.
- AC-2.1-2 (REQ-2.1-2): Given any customers, when searching "a", then the response status is 400.

## Non-functional requirements
- none

## Architecture
ADRs: ADR-001
Tech requirements:
- The endpoint lives in src/api/search_controller.py.

## Skills
- python: all code
- api-design: the search endpoint

## Out of scope
- Fuzzy matching.

## Open questions
- none

## Approval
<!-- The user approves by adding a line "Approved-by: <name> (<date>)" below. Agents cannot. -->
EOF
out=$(hook "$F" pre-tool-use "$(swrite analyst "$SPEC" "$SPEC_TEXT")" 2>&1)
contains "skill gate: a spec needs requirements-writing" "requirements-writing" "$out"
hook "$F" post-tool-use "$(sread analyst "$F/.claude/skills/requirements-writing/SKILL.md")"
expect 0 "skill gate: allowed once the skill was read" hook "$F" pre-tool-use "$(swrite analyst "$SPEC" "$SPEC_TEXT")"
printf '%s\n' "$SPEC_TEXT" > "$SPEC"
cat > "$F/backbone/specs/9.9.md" <<'EOF'
# Spec 9.9: Broken
## Requirements
- REQ-9.9-1: The system shall do one thing.
- REQ-9.9-2: The system shall do another.
## Acceptance criteria
- AC-9.9-1 (REQ-9.9-1): It works.
- AC-9.9-2: Given x, when y, then z.
## Architecture
ADRs: ADR-042
## Skills
- cobol: everything
## Open questions
- Which database? TODO
EOF
out=$(python3 "$F/scripts/harness/lib/harness.py" spec-check 9.9)
contains "spec-check: AC not in Given/When/Then" "AC-9.9-1 is not written as Given" "$out"
contains "spec-check: AC without requirement" "AC-9.9-2 does not reference" "$out"
contains "spec-check: requirement without AC" "REQ-9.9-2 has no acceptance criterion" "$out"
contains "spec-check: missing ADR" "ADR-042 is referenced but not found" "$out"
contains "spec-check: unknown skill" "skill 'cobol' does not exist" "$out"
contains "spec-check: open questions" "open questions remain" "$out"
contains "spec-check: stubs" "placeholders" "$out"
expect 0 "spec-check passes a valid spec" python3 "$F/scripts/harness/lib/harness.py" spec-check 2.1

section "pipeline: grill and approve"
printf '%s\n' "- [ ] **Task 2.1: Customer search** (spec: backbone/specs/2.1.md)" >> "$FT"
START="$(edit_json "$FT" "- [ ] **Task 2.1" "- [WIP] **Task 2.1")"
out=$(hook "$F" pre-tool-use "$START" 2>&1)
contains "start gate: needs grilling" "has not been grilled" "$out"
out=$(HARNESS_SPEC_GATE=off hook "$F" pre-tool-use "$START" 2>&1; echo "exit=$?")
contains "start gate can be switched off by the user" "exit=0" "$out"
expect 2 "griller without verdict JSON is sent back" hook "$F" grill-stop "$(stop_json griller "Mostly fine.")"
hook "$F" grill-stop "$(stop_json griller "$(greport fail blocker)")" >/dev/null
out=$(hook "$F" pre-tool-use "$START" 2>&1)
contains "start gate: a failed grill blocks" "the griller failed the spec" "$out"
out=$(hook "$F" grill-stop "$(stop_json griller "$(greport pass major)")")
contains "grill: a pass with an open major question is a fail" "major question" "$out"
out=$(hook "$F" grill-stop "$(stop_json griller "$(greport pass none)")")
contains "grill: a clean pass is recorded" "task 2.1: PASS" "$out"
out=$(hook "$F" pre-tool-use "$START" 2>&1)
contains "start gate: needs the user's approval" "has not approved the spec" "$out"
echo "- Revisit if more modules adopt it." >> "$F/backbone/adr/ADR-001-adopt-agentic-harness.md"
out=$(hook "$F" pre-tool-use "$START" 2>&1)
contains "start gate: changing a referenced ADR makes the grill stale" "changed after the griller passed" "$out"
hook "$F" grill-stop "$(stop_json griller "$(greport pass none)")" >/dev/null
APPROVE_MARK='<!-- The user approves by adding a line "Approved-by: <name> (<date>)" below. Agents cannot. -->'
out=$(hook "$F" pre-tool-use "$(edit_json "$SPEC" "$APPROVE_MARK" "$APPROVE_MARK
Approved-by: Claude")" 2>&1)
contains "agents cannot approve a spec" "Only the user may add" "$out"
echo "Approved-by: Peter (2026-10-04)" >> "$SPEC"
expect 0 "start gate: valid + grilled + approved starts the task" hook "$F" pre-tool-use "$START"
out=$(hook "$F" pre-tool-use "$(edit_json "$SPEC" "- Fuzzy matching." "- Fuzzy and phonetic matching.")" 2>&1)
contains "an approved spec is frozen" "approved and therefore frozen" "$out"
out=$(hook "$F" pre-tool-use "$(edit_json "$SPEC" "Approved-by: Peter (2026-10-04)" "")" 2>&1)
contains "agents cannot remove an approval" "Only the user may add" "$out"
contains "spec-check shows the whole state" "approved" "$(python3 "$F/scripts/harness/lib/harness.py" spec-check 2.1)"
python3 - "$FT" <<'EOF'
import sys
p = sys.argv[1]; s = open(p).read()
open(p, "w").write(s.replace("- [ ] **Task 2.1", "- [WIP] **Task 2.1", 1))
EOF
contains "session start names the WIP task and its spec" "backbone/specs/2.1.md" "$(hook "$F" session-start '{}')"

section "pipeline: build (skill gate and write scopes)"
CODE="$F/src/api/search_controller.py"
out=$(hook "$F" pre-tool-use "$(swrite impl "$CODE" "def search(q): ...")" 2>&1)
contains "skill gate: code needs the routed language skill" "python:" "$out"
contains "skill gate: the API layer needs api-design" "api-design:" "$out"
hook "$F" post-tool-use "$(sskill impl python)"
out=$(hook "$F" pre-tool-use "$(swrite impl "$CODE" "def search(q): ...")" 2>&1)
lacks "skill gate: a skill invoked through the Skill tool counts" "python:" "$out"
hook "$F" post-tool-use "$(sread impl "$F/.claude/skills/api-design/SKILL.md")"
hook "$F" post-tool-use "$(sskill impl code-quality)"
expect 0 "skill gate: allowed with every required skill" hook "$F" pre-tool-use "$(swrite impl "$CODE" "def search(q): ...")"
out=$(hook "$F" pre-tool-use "$(swrite other "$F/src/util.py" "x = 1")" 2>&1)
contains "skill gate: skills are per session, and spec skills apply to all code" "api-design:" "$out"
expect 2 "implementer may not edit the task log" guard "$F" implementer "$(edit_json "$FT" "a" "b")"
expect 2 "implementer may not edit specs" guard "$F" implementer "$(edit_json "$SPEC" "a" "b")"
expect 0 "implementer may edit code" guard "$F" implementer "$(edit_json "$CODE" "a" "b")"
expect 2 "analyst may not edit code" guard "$F" analyst "$(edit_json "$CODE" "a" "b")"
expect 0 "analyst may edit specs" guard "$F" analyst "$(edit_json "$SPEC" "a" "b")"
expect 0 "architect may edit ADRs" guard "$F" architect "$(edit_json "$F/backbone/adr/ADR-002-x.md" "a" "b")"
expect 2 "architect may not edit code" guard "$F" architect "$(edit_json "$CODE" "a" "b")"
expect 0 "scribe may edit 6-MEMORY.md" guard "$F" scribe "$(edit_json "$F/backbone/6-MEMORY.md" "a" "b")"
expect 2 "scribe may not edit code" guard "$F" scribe "$(edit_json "$CODE" "a" "b")"

section "pipeline: judge"
mkdir -p "$F/src/api" "$F/tests"
printf 'def search(q):  # implements AC-2.1-2 validation\n    return []\n' > "$CODE"
printf 'def test_ac_2_1_1():  # AC-2.1-1\n    assert True\n' > "$F/tests/test_search.py"
FINISH="$(edit_json "$FT" "- [WIP] **Task 2.1" "- [x] **Task 2.1")"
out=$(hook "$F" pre-tool-use "$FINISH" 2>&1)
contains "judge gate: needs a verdict" "has no judge verdict" "$out"
out=$(hook "$F" judge-stop "$(stop_json judge "$(jreport pass passed AC-2.1-1 AC-2.1-2)")")
contains "judge: an AC mentioned only outside tests is untraced" "no test file references AC-2.1-2" "$out"
out=$(hook "$F" pre-tool-use "$FINISH" 2>&1)
contains "judge gate: a fail blocks with the round count" "round 1 of 2" "$out"
printf 'def test_ac_2_1_2():  # AC-2.1-2\n    assert True\n' >> "$F/tests/test_search.py"
out=$(hook "$F" judge-stop "$(stop_json judge "$(jreport pass passed AC-2.1-1)")")
contains "judge: every AC in the spec must be evaluated" "AC-2.1-2 was not evaluated" "$out"
out=$(hook "$F" pre-tool-use "$FINISH" 2>&1)
contains "judge gate: max rounds forces escalation" "Stop retrying" "$out"
out=$(hook "$F" judge-stop "$(stop_json judge "$(jreport pass passed AC-2.1-1 AC-2.1-2)")")
contains "judge: a traced, tested pass is recorded" "task 2.1: PASS" "$out"
expect 0 "judge gate: a current pass finishes the task" hook "$F" pre-tool-use "$FINISH"
echo "- 2026-10-04: search needs an index" >> "$F/backbone/6-MEMORY.md"
expect 0 "judge gate: backbone edits keep the verdict current" hook "$F" pre-tool-use "$FINISH"
echo "# tweak" >> "$CODE"
out=$(hook "$F" pre-tool-use "$FINISH" 2>&1)
contains "judge gate: a code change makes the pass stale" "code changed after the judge passed" "$out"
out=$(hook "$F" judge-stop "$(stop_json judge "$(jreport pass not-run AC-2.1-1 AC-2.1-2)")")
contains "judge: tests that did not run fail the verdict" "tests not-run" "$out"
expect 2 "rewording the task does not dodge the gate" hook "$F" pre-tool-use "$(edit_json "$FT" "- [WIP] **Task 2.1: Customer search**" "- [x] **Task 2.1: Customer search (done)**")"
expect 0 "abandoning (back to [ ]) is allowed" hook "$F" pre-tool-use "$(edit_json "$FT" "- [WIP] **Task 2.1" "- [ ] **Task 2.1")"
TR="$WORK/transcript.jsonl"
python3 - "$TR" "$(jreport pass passed AC-2.1-1 AC-2.1-2)" <<'EOF'
import json, sys
with open(sys.argv[1], "w") as f:
    f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "judge task 2.1"}}) + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": sys.argv[2]}]}}) + "\n")
EOF
hook "$F" judge-stop "{\"agent_type\":\"judge\",\"transcript_path\":\"$TR\"}" >/dev/null
expect 0 "judge: verdict read from the transcript when the message is absent" hook "$F" pre-tool-use "$FINISH"
expect 0 "other agents' stops are ignored" hook "$F" judge-stop '{"agent_type":"analyst","last_assistant_message":"no json"}'
V="$F/backbone/.verdicts/2.1.judge.json"
contains "verdicts keep the full history" '"claimed": "pass"' "$(cat "$V")"
expect 2 "agents cannot write verdicts" hook "$F" pre-tool-use "$(write_json "$V" '{"history":[{"verdict":"pass"}]}')"
expect 2 "agents cannot write verdicts via the shell" hook "$F" pre-tool-use "$(bash_json "echo '{}' > backbone/.verdicts/2.1.judge.json")"
expect 0 "agents can read verdicts via the shell" hook "$F" pre-tool-use "$(bash_json "cat backbone/.verdicts/2.1.judge.json")"

section "user-only settings and health"
C="$F/backbone/harness.conf"
for key in HARNESS_SPEC_GATE HARNESS_SKILL_GATE HARNESS_JUDGE_GATE; do
  expect 2 "agents cannot switch off $key" hook "$F" pre-tool-use "$(edit_json "$C" "$key=\"on\"" "$key=\"off\"")"
done
expect 2 "agents cannot raise the round limit" hook "$F" pre-tool-use "$(edit_json "$C" 'HARNESS_JUDGE_MAX_ROUNDS="2"' 'HARNESS_JUDGE_MAX_ROUNDS="9"')"
expect 0 "agents can set the build command" hook "$F" pre-tool-use "$(edit_json "$C" 'HARNESS_BUILD_CMD=""' 'HARNESS_BUILD_CMD="make"')"
echo '\.sql$ | sql-migrations | Migrations.' >> "$F/backbone/routing.conf"
contains "doctor warns about routes to missing skills" "missing skill 'sql-migrations'" "$("$F/scripts/harness/doctor.sh")"
echo 'broken route line' >> "$F/backbone/routing.conf"
expect 1 "doctor reports an invalid route" "$F/scripts/harness/doctor.sh"
sed -i.bak '/broken route line/d' "$F/backbone/routing.conf" && rm -f "$F/backbone/routing.conf.bak"
mv "$F/.claude/agents/judge.md" "$WORK/judge.md.bak"
expect 1 "doctor reports a missing pipeline agent" "$F/scripts/harness/doctor.sh"
mv "$WORK/judge.md.bak" "$F/.claude/agents/judge.md"

section "skill format contract (core and profiles)"
out=$(python3 - "$HARNESS" <<'EOF'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
skills = {}
for base in [root / "payload/owned/.claude/skills"] + sorted(root.glob("catalog/*/install/.claude/skills")) + sorted(root.glob("catalog/*/options/*/install/.claude/skills")):
    for f in sorted(base.glob("*/SKILL.md")):
        skills[f.parent.name] = f
problems = []
for name, f in sorted(skills.items()):
    text = f.read_text()
    lines = text.splitlines()
    if not text.startswith("---\n"):
        problems.append("%s: frontmatter is not the first thing in the file" % name)
        continue
    front = text.split("---", 2)[1]
    fields = dict(re.findall(r"^([a-z-]+):\s*(.+)$", front, re.M))
    for key in ("name", "description", "applies-to", "last-verified"):
        if not fields.get(key):
            problems.append("%s: missing frontmatter field %s" % (name, key))
    if fields.get("name") != name:
        problems.append("%s: name %r does not match its folder" % (name, fields.get("name")))
    if len(lines) > 220:
        problems.append("%s: SKILL.md has %d lines (limit 220)" % (name, len(lines)))
    linked = re.search(r"^## Linked skills\s*$(.*?)(^## |\Z)", text, re.M | re.S)
    if not linked:
        problems.append("%s: no '## Linked skills' section" % name)
    else:
        for ref in re.findall(r"^\s*[-*]\s+`([a-z0-9-]+)`", linked.group(1), re.M):
            if ref not in skills:
                problems.append("%s: links to unknown skill %s" % (name, ref))
    for extra in f.parent.glob("*.md"):
        if extra.name != "SKILL.md" and len(extra.read_text().splitlines()) > 320:
            problems.append("%s/%s: linked file over 320 lines" % (name, extra.name))
print("skills:", " ".join(sorted(skills)))
print("\n".join(problems) or "OK")
EOF
)
contains "every skill follows the format contract" "OK" "$out"
for s in requirements-writing adr-writing architecture api-design openapi code-quality module-testing security changelog \
         java java-test java-review quarkus quarkus-cdi jdbi containers container-security; do
  contains "skill present: $s" " $s" " ${out%%$'\n'*} "
done
leaks=$(grep -rlE -- '-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b' "$HARNESS/payload" "$HARNESS/catalog" 2>/dev/null)
expect 0 "no payload file trips the core secret rules" test -z "$leaks"

section "stack-neutral install"
Q="$WORK/qk"
new_repo "$Q"
out=$("$HARNESS/bootstrap.sh" "$Q" 2>&1)
contains "install adopts no stack" "stack packs adopted: none" "$out"
lacks "install has no profile option" "profile" "$("$HARNESS/bootstrap.sh" --help 2>&1)"
[ -f "$Q/scripts/harness/catalog/java/pack.json" ] && ok "catalog shipped inert" || bad "catalog shipped inert"
[ ! -d "$Q/.claude/skills/java" ] && ok "no stack skill installed before a decision" || bad "no stack skill installed before a decision"
lacks "no stack routes before a decision" "java" "$(grep -v '^#' "$Q/backbone/routing.conf")"
lacks "seeded config names no build tool" "gradle" "$(cat "$Q/backbone/harness.conf")"
contains "session start says the stack is decided in design" "decided in the design phase" "$(hook "$Q" session-start '{}')"
out=$(python3 "$Q/scripts/harness/lib/harness.py" catalog)
contains "catalog lists packs" "quarkus" "$out"
contains "catalog shows option groups" "choose exactly one build-tool: gradle | maven" "$out"
contains "catalog shows requirements" "requires: java" "$out"

section "adopting packs from an accepted ADR"
H="$Q/scripts/harness/lib/harness.py"
ADR2="$Q/backbone/adr/ADR-002-stack.md"
cat > "$ADR2" <<'EOF'
# ADR-002: Stack

## Status
Proposed

## Date
2026-10-05

## Context
A JSON API with a relational database, shipped as containers.

## Decision
Java 25 with Gradle, Quarkus with hexagonal layering and JSR-330 use cases, JDBI SQL-first without any ORM,
JUnit 5 + AssertJ, no Lombok, Podman images. Catalog packs: java, quarkus, jdbi, container.

## Alternatives considered
- Spring Boot with JPA: heavier, ORM conflicts with SQL-first.

## Consequences
- Agents load the adopted stack skills.
EOF
ALL="--with gradle,junit5-assertj,no-lombok,no-spring,hexagonal-layers,named-use-cases,no-orm,flyway,podman"
out=$(python3 "$H" adopt java,quarkus,jdbi,container --adr ADR-002 $ALL 2>&1; echo "exit=$?")
contains "adoption refuses a Proposed ADR" "is not Accepted" "$out"
sed -i.bak 's/^Proposed$/Accepted/' "$ADR2" && rm -f "$ADR2.bak"
out=$(python3 "$H" adopt quarkus --adr ADR-002 $ALL 2>&1)
contains "a pack's requirements must be adopted too" "requires the java pack" "$out"
out=$(python3 "$H" adopt java --adr ADR-002 --with junit5-assertj 2>&1)
contains "every option must be decided: build tool" "choose the build-tool" "$out"
contains "every option must be decided: yes/no options" "decide 'no-lombok'" "$out"
out=$(python3 "$H" adopt java --adr ADR-002 --with gradle,maven,junit5-assertj,no-lombok 2>&1)
contains "only one option per group" "choose only one build-tool" "$out"
out=$(python3 "$H" adopt java --adr ADR-003 --with gradle 2>&1)
contains "the ADR must exist" "ADR-003 not found" "$out"
out=$(python3 "$H" adopt java,quarkus,jdbi,container --adr ADR-002 $ALL --dry-run 2>&1)
contains "dry run shows the plan" "Would adopt" "$out"
[ ! -d "$Q/.claude/skills/java" ] && ok "dry run changes nothing" || bad "dry run changes nothing"
expect 0 "adopts all four packs" python3 "$H" adopt java,quarkus,jdbi,container --adr ADR-002 $ALL
for f in .claude/skills/java/SKILL.md .claude/skills/java-test/SKILL.md .claude/skills/java-review/SKILL.md \
         .claude/skills/quarkus/SKILL.md .claude/skills/quarkus-cdi/SKILL.md .claude/skills/jdbi/SKILL.md \
         .claude/skills/containers/SKILL.md .claude/skills/container-security/SKILL.md; do
  [ -f "$Q/$f" ] && ok "adopted: $f" || bad "adopted: $f"
done
NT=$(ls "$Q"/scripts/harness/packs/quarkus/native-test.sh 2>/dev/null)
[ -x "$NT" ] && ok "native-test.sh installed and executable" || bad "native-test.sh installed and executable"
expect 0 "native-test.sh parses" bash -n "$NT"
expect 0 "native-test.sh --help" "$NT" --help
conf=$(cat "$Q/backbone/harness.conf")
contains "build tool option sets the test command" 'HARNESS_TEST_CMD="./gradlew test"' "$conf"
contains "engine option sets the container engine" 'HARNESS_CONTAINER_ENGINE="podman"' "$conf"
contains "rules are marked with the ADR" "# >>> adopted pack: java (ADR-002" "$(cat "$Q/backbone/guardrails.conf")"
contains "routes are marked with the ADR" "# >>> adopted pack: quarkus (ADR-002" "$(cat "$Q/backbone/routing.conf")"
contains "session start lists adopted packs" "java via ADR-002" "$(hook "$Q" session-start '{}')"
J="$Q/src/main/java/com/acme/customer"
guard_msg() { hook "$Q" pre-tool-use "$(write_json "$1" "$2")" 2>&1; }
contains "no-spring: Spring annotations are blocked" "Spring" "$(guard_msg "$J/infra/CustomerController.java" '@RestController class CustomerController {}')"
contains "hexagonal-layers: framework imports in domain are blocked" "framework-free" "$(guard_msg "$J/domain/Customer.java" 'import io.quarkus.runtime.Startup;')"
contains "hexagonal-layers: domain may not import the app layer" "must not import the application" "$(guard_msg "$J/domain/Customer.java" 'import com.acme.customer.app.CreateCustomer;')"
contains "hexagonal-layers: app may not import infra" "must not import infrastructure" "$(guard_msg "$J/app/CreateCustomer.java" 'import com.acme.customer.infra.CustomerJdbiRepository;')"
contains "no-orm: Panache is blocked" "Hibernate ORM" "$(guard_msg "$J/infra/CustomerEntity.java" 'import io.quarkus.hibernate.orm.panache.PanacheEntity;')"
contains "no-orm: JPA is blocked" "JPA" "$(guard_msg "$J/infra/CustomerEntity.java" 'import jakarta.persistence.Entity;')"
lacks "no-orm: Hibernate Validator stays allowed" "Hibernate ORM" "$(guard_msg "$J/infra/CustomerDto.java" 'import org.hibernate.validator.constraints.Length;')"
contains "no-lombok: Lombok is blocked" "Lombok" "$(guard_msg "$J/infra/CustomerDto.java" 'import lombok.Data;')"
contains "junit5-assertj: JUnit assertions are blocked in tests" "Use AssertJ" "$(guard_msg "$Q/src/test/java/com/acme/CustomerTest.java" 'import static org.junit.jupiter.api.Assertions.assertEquals;')"
contains "container: secrets in ENV are blocked" "Secrets in ENV/ARG" "$(guard_msg "$Q/Containerfile" 'ENV DB_PASSWORD=hunter2')"
contains "container: engine socket mounts are blocked" "engine socket" "$(guard_msg "$Q/compose.yaml" '      - /run/podman/podman.sock:/var/run/docker.sock')"
contains "container: privileged gets a warning after the edit" "Privileged containers" "$(hook "$Q" post-tool-use "$(write_json "$Q/podman-compose.yml" '    privileged: true')")"
out=$(guard_msg "$J/app/CreateCustomer.java" 'package com.acme.customer.app;')
contains "routing: Java code needs the java skill" "java:" "$out"
contains "routing: Quarkus bean code needs quarkus-cdi" "quarkus-cdi:" "$out"
contains "routing: every source file needs code-quality" "code-quality:" "$out"
contains "routing: migrations need the jdbi skill" "jdbi:" "$(guard_msg "$Q/src/main/resources/db/migration/V1__customers.sql" 'create table customer (id uuid primary key);')"
contains "routing: Containerfiles need container-security" "container-security:" "$(guard_msg "$Q/Containerfile" 'FROM registry.access.redhat.com/ubi9/ubi-minimal:9.6')"
mkdir -p "$J/infra"
printf 'package com.acme.customer.infra;\n@Service\nclass LegacyService {}\n' > "$J/infra/LegacyService.java"
contains "scan: session start reports existing violations" "LegacyService.java" "$(hook "$Q" session-start '{}')"
out=$(python3 "$H" scan; echo "exit=$?")
contains "scan: lists the violation" "Spring" "$out"
contains "scan: exits 1 on blocking drift" "exit=1" "$out"
contains "doctor mentions the drift" "existing rule violation" "$("$Q/scripts/harness/doctor.sh")"
rm "$J/infra/LegacyService.java"
expect 0 "update keeps adopted packs" "$HARNESS/update.sh" "$Q"
[ -f "$Q/.claude/skills/quarkus-cdi/SKILL.md" ] && ok "adopted skills survive updates" || bad "adopted skills survive updates"
out=$(python3 "$H" adopt --remove java 2>&1)
contains "a required pack cannot be removed alone" "required by" "$out"
expect 0 "re-adopting java with other options" python3 "$H" adopt java --adr ADR-002 --with maven,no-lombok --without junit5-assertj
[ ! -f "$Q/.claude/skills/java-test/SKILL.md" ] && ok "a dropped option's skill is removed" || bad "a dropped option's skill is removed"
contains "re-adoption replaces the conf" 'HARNESS_TEST_CMD="./mvnw -q test"' "$(cat "$Q/backbone/harness.conf")"
expect 1 "only one block per pack" test "$(grep -c '# >>> adopted pack: java ' "$Q/backbone/guardrails.conf")" -gt 1
expect 0 "removing packs" python3 "$H" adopt --remove quarkus,jdbi,container
[ ! -f "$Q/.claude/skills/quarkus/SKILL.md" ] && ok "removed packs' skills are gone" || bad "removed packs' skills are gone"
lacks "removed packs' rules are gone" "adopted pack: quarkus" "$(cat "$Q/backbone/guardrails.conf")"
sed -i.bak 's/^Accepted$/Superseded by ADR-003/' "$ADR2" && rm -f "$ADR2.bak"
contains "doctor flags packs whose ADR is no longer accepted" "no longer Accepted" "$("$Q/scripts/harness/doctor.sh")"

section "warnings: shell commands, commit scope, commit nudge"
contains "risky shell commands get a warning" "forced branch delete" "$(hook "$Q" post-tool-use "$(bash_json 'git branch -D old-feature')")"
expect 0 "harmless shell commands stay silent" test -z "$(hook "$Q" post-tool-use "$(bash_json 'git branch -d merged-feature')")"
git -C "$Q" add -A >/dev/null; SKIP_BUILD=1 git -C "$Q" commit -qm "chore: adopt agentic harness" >/dev/null 2>&1
echo "x" > "$Q/README.md"; git -C "$Q" add README.md
out=$(SKIP_BUILD=1 git -C "$Q" commit -m "docs(customer): add readme" 2>&1)
contains "commit scope that matches no staged path is warned about" "matches no path" "$out"
echo "y" >> "$Q/README.md"; git -C "$Q" add README.md
out=$(SKIP_BUILD=1 git -C "$Q" commit -m "docs: update readme" 2>&1)
lacks "no scope, no warning" "matches no path" "$out"
echo "z" >> "$Q/README.md"
out=$(HARNESS_COMMIT_NUDGE=1 hook "$Q" stop '{}')
contains "stop nudges to commit uncommitted work when no task is open" "uncommitted changes" "$out"
expect 0 "the nudge can be switched off" test -z "$(HARNESS_COMMIT_NUDGE=0 hook "$Q" stop '{}')"

section "decision layer (advisory, provider-neutral)"
D="$WORK/decide"
new_repo "$D"
"$HARNESS/bootstrap.sh" "$D" >/dev/null
git -C "$D" add -A >/dev/null; SKIP_BUILD=1 git -C "$D" commit -qm "chore: adopt agentic harness" >/dev/null 2>&1
FAKE="$WORK/fake-decider.py"
cat > "$FAKE" <<'EOF'
import json, os, sys
payload = json.load(sys.stdin)
open(os.environ["FAKE_MARKER"], "w").write(json.dumps(payload))
if os.environ.get("FAKE_EXIT"):
    sys.exit(int(os.environ["FAKE_EXIT"]))
print(json.dumps({
    "fit": {"choice": os.environ.get("FAKE_FIT", "accurate"), "confidence": float(os.environ.get("FAKE_CONF", "0.9"))},
    "unmentioned": {"p": 0.1},
    "leftovers": {"p": 0.05},
}))
EOF
export FAKE_MARKER="$WORK/decider-called.json"
setconf() { python3 - "$D/backbone/harness.conf" "$@" <<'EOF'
import re, sys
path, pairs = sys.argv[1], sys.argv[2:]
text = open(path).read()
for pair in pairs:
    key, value = pair.split("=", 1)
    text = re.sub(r'^%s=.*$' % key, '%s="%s"' % (key, value), text, flags=re.M)
open(path, "w").write(text)
EOF
}
dcommit() { echo "$1" >> "$D/feature.txt"; git -C "$D" add feature.txt; SKIP_BUILD=1 git -C "$D" commit -m "$2" 2>&1; }
LOG="$D/.git/harness/decisions.jsonl"
out=$(dcommit a "feat: add feature file")
[ ! -f "$FAKE_MARKER" ] && [ ! -f "$LOG" ] && ok "off by default: no calls, no log" || bad "off by default: no calls, no log"
setconf HARNESS_DECISION_PROVIDER=command HARNESS_DECISION_MODE=shadow "HARNESS_DECISION_CMD=python3 $FAKE"
contains "doctor: a provider without an approving ADR is an error" "not authorised" "$("$D/scripts/harness/doctor.sh")"
out=$(dcommit b "feat: extend feature file")
[ ! -f "$FAKE_MARKER" ] && ok "no ADR, no call: project data stays local" || bad "no ADR, no call: project data stays local"
cat > "$D/backbone/adr/ADR-002-decision-provider.md" <<'EOF'
# ADR-002: Advisory decision provider

## Status
Accepted

## Date
2026-10-05

## Context
Commit messages drift from the diffs they describe.

## Decision
Use the command decision provider (and later possibly claude) in shadow mode for the commit-message decision.

## Alternatives considered
- No decision layer: misses message/diff drift.

## Consequences
- Staged diffs are sent to the configured provider.
EOF
setconf HARNESS_DECISION_ADR=ADR-002
lacks "doctor: an approving ADR authorises the provider" "not authorised" "$("$D/scripts/harness/doctor.sh")"
out=$(dcommit c "feat: extend feature file again")
[ -f "$FAKE_MARKER" ] && ok "shadow: the provider is called" || bad "shadow: the provider is called" "$out"
payload=$(cat "$FAKE_MARKER" 2>/dev/null)
contains "state carries the message subject" "extend feature file again" "$payload"
contains "state carries the staged diff" "+c" "$payload"
contains "questions come from decisions.json" "debugging leftovers" "$payload"
lacks "shadow: nothing is shown" "advisory" "$out"
contains "shadow: the call is logged" '"decision": "commit-message"' "$(tail -1 "$LOG")"
setconf HARNESS_DECISION_MODE=advise
out=$(FAKE_FIT=mismatch FAKE_CONF=0.92 dcommit d "docs: fix typo in readme"; echo "exit=$?")
contains "advise: a confident mismatch is shown" "harness decision (advisory)" "$out"
contains "advise: it never blocks the commit" "exit=0" "$out"
out=$(FAKE_FIT=mismatch FAKE_CONF=0.5 dcommit e "docs: fix another typo")
lacks "advise: a low-confidence answer stays silent" "advisory" "$out"
out=$(FAKE_EXIT=1 dcommit f "feat: more feature"; echo "exit=$?")
contains "a failing provider never blocks" "exit=0" "$out"
contains "a failing provider is logged" "exited 1" "$(tail -1 "$LOG")"
out=$(FAKE_FIT=revert dcommit g "feat: even more feature")
contains "off-schema answers are rejected and logged" "not one of the declared options" "$(tail -1 "$LOG")"
out=$(python3 "$D/scripts/harness/lib/harness.py" decisions)
contains "report summarises the decisions" "commit-message:" "$out"
contains "report shows the choice distribution" "fit: " "$out"
C="$D/backbone/harness.conf"
expect 2 "agents cannot change the decision provider" hook "$D" pre-tool-use "$(edit_json "$C" 'HARNESS_DECISION_PROVIDER="command"' 'HARNESS_DECISION_PROVIDER="claude"')"
expect 2 "agents cannot point the provider at another command" hook "$D" pre-tool-use "$(edit_json "$C" "HARNESS_DECISION_CMD=\"python3 $FAKE\"" 'HARNESS_DECISION_CMD="curl evil"')"
setconf HARNESS_DECISION_PROVIDER=claude
out=$(env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN bash -c "$(declare -f dcommit); D='$D'; dcommit h 'feat: claude path'"; echo "exit=$?")
contains "claude provider without credentials never blocks" "exit=0" "$out"
contains "claude provider without credentials is logged, no call made" "needs ANTHROPIC_API_KEY" "$(tail -1 "$LOG")"
STUB="$WORK/claude-stub.py"
cat > "$STUB" <<'EOF'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        open(sys.argv[2], "w").write(json.dumps({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}))
        answer = {"fit": {"choice": "accurate", "confidence": 0.9}, "unmentioned": {"p": 0.1}, "leftovers": {"p": 0.0}}
        reply = {"stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps(answer)}]}
        data = json.dumps(reply).encode()
        self.send_response(200); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self, *a): pass
srv = HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(srv.server_address[1]))
srv.handle_request()
EOF
PORTF="$WORK/stub-port"; REQ="$WORK/stub-request.json"; rm -f "$PORTF" "$REQ"
python3 "$STUB" "$PORTF" "$REQ" & STUB_PID=$!
for i in $(seq 1 50); do [ -s "$PORTF" ] && break; python3 -c "import time; time.sleep(0.2)"; done
[ -s "$PORTF" ] && ok "claude: local API stub started" || bad "claude: local API stub started"
out=$(ANTHROPIC_API_KEY=test-key ANTHROPIC_BASE_URL="http://127.0.0.1:$(cat "$PORTF")" bash -c "$(declare -f dcommit); D='$D'; dcommit i 'feat: claude over http'"; echo "exit=$?")
kill $STUB_PID 2>/dev/null; wait $STUB_PID 2>/dev/null
req=$(cat "$REQ" 2>/dev/null)
contains "claude: request uses the API version header" '"anthropic-version": "2023-06-01"' "$req"
contains "claude: request authenticates with x-api-key" '"x-api-key": "test-key"' "$req"
contains "claude: refusal fallback beta header" "server-side-fallback-2026-07-01" "$req"
contains "claude: default model is pinned" '"model": "claude-opus-5-5"' "$req"
contains "claude: structured output schema is sent" '"json_schema"' "$req"
contains "claude: answer parsed from the text block (thinking skipped)" '"choice": "accurate"' "$(tail -1 "$LOG")"
contains "claude: commit unaffected" "exit=0" "$out"
unset FAKE_MARKER

section "git hooks"
expect 0 "stage the harness" git -C "$P" add -A
expect 0 "commit with a valid message" git -C "$P" commit -qm "chore: adopt agentic harness"
echo "x" > "$P/x.txt"; git -C "$P" add x.txt
expect 1 "commit-msg rejects a free-form message" git -C "$P" commit -qm "added stuff"
expect 1 "commit-msg rejects a long subject" git -C "$P" commit -qm "feat: $(printf 'a%.0s' $(seq 1 80))"
expect 0 "commit-msg accepts scope and breaking marker" git -C "$P" commit -qm "feat(api)!: drop v1 endpoints"
printf "secret = 'AKIAIOSFODNN7EXAMPLE'\n" > "$P/leak.py"; git -C "$P" add leak.py
expect 1 "pre-commit blocks a staged secret" git -C "$P" commit -qm "fix: add config"
git -C "$P" rm -q --cached leak.py; rm "$P/leak.py"
echo "y" > "$P/y.txt"; git -C "$P" add y.txt
HARNESS_BUILD_CMD=false expect 1 "pre-commit fails on a failing build" git -C "$P" commit -qm "fix: y"
HARNESS_BUILD_CMD=false SKIP_BUILD=1 expect 0 "SKIP_BUILD=1 skips the build" git -C "$P" commit -qm "fix: y"

section "post-commit Definition of Done feedback"
echo "z" > "$P/z.txt"; git -C "$P" add z.txt; git -C "$P" commit -qm "feat: z"
out=$(hook "$P" post-tool-use "$(bash_json 'git commit -m "feat: z"')")
contains "reminds about 3-TASKS.md" "3-TASKS.md" "$out"
contains "reports the open WIP task" "Still [WIP]" "$out"
printf '# ADR-002: Use pathlib\n\n## Status\nAccepted\n\n## Context\nfiles\n' > "$P/backbone/adr/ADR-002-use-pathlib.md"
git -C "$P" add -A; git -C "$P" commit -qm "docs: record decision"
out=$(hook "$P" post-tool-use "$(bash_json 'git add -A && git commit -m "docs: record decision"')")
contains "flags an incomplete ADR" "section '## Decision' is missing" "$out"
out=$(hook "$P" post-tool-use "$(bash_json 'git log --oneline')")
expect 0 "ignores non-commit commands" test -z "$out"

section "worktrees"
git -C "$P" worktree add -q "$WORK/demo-wt" -b wt-test
echo "w" > "$WORK/demo-wt/w.txt"; git -C "$WORK/demo-wt" add w.txt
expect 1 "hooks run in a linked worktree" git -C "$WORK/demo-wt" commit -qm "bad message"

section "update"
H2="$WORK/harness-v2"
mkdir -p "$H2"; cp -R "$HARNESS/." "$H2/"; rm -rf "$H2/.git"
echo "99.0.0-test" > "$H2/VERSION"
echo "Upstream change." >> "$H2/payload/owned/AGENTS.md"
echo "Upstream workflow change." >> "$H2/payload/owned/backbone/8-WORKFLOW.md"
echo "# new" > "$H2/payload/owned/backbone/NEW-DOC.md"
rm "$H2/payload/owned/backbone/SKILLS.md"
echo "Local workflow tweak." >> "$P/backbone/8-WORKFLOW.md"
python3 - "$P/.claude/settings.json" <<'EOF'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["hooks"]["PreToolUse"].append({"matcher": "Read", "hooks": [{"type": "command", "command": "echo custom-hook"}]})
s["permissions"]["allow"].append("Bash(make:*)")
s["model"] = "opus"
json.dump(s, open(p, "w"), indent=2)
EOF
expect 0 "status works" "$H2/update.sh" status "$P"
contains "status lists the upstream change" "update available" "$("$H2/update.sh" status "$P")"
cp -R "$P" "$WORK/dry"
"$H2/update.sh" "$WORK/dry" --dry-run >/dev/null 2>&1
contains "dry run changes nothing" "\"harness_version\": \"$(cat "$HARNESS/VERSION")\"" "$(cat "$WORK/dry/backbone/.harness-lock.json")"
expect 1 "update reports a conflict" "$H2/update.sh" "$P"
contains "unmodified harness file updated" "Upstream change." "$(cat "$P/AGENTS.md")"
contains "locally edited file kept" "Local workflow tweak." "$(cat "$P/backbone/8-WORKFLOW.md")"
[ -f "$P/backbone/8-WORKFLOW.md.harness-new" ] && ok "conflict written to .harness-new" || bad "conflict written to .harness-new"
[ -f "$P/backbone/NEW-DOC.md" ] && ok "new harness file added" || bad "new harness file added"
[ ! -f "$P/backbone/SKILLS.md" ] && ok "dropped harness file removed" || bad "dropped harness file removed"
contains "project files untouched" "Use pathlib" "$(cat "$P/backbone/adr/ADR-002-use-pathlib.md")"
settings=$(cat "$P/.claude/settings.json")
contains "custom hook kept" "custom-hook" "$settings"
contains "custom permission kept" "Bash(make:*)" "$settings"
contains "other settings kept" '"model": "opus"' "$settings"
count=$(grep -c "hook pre-tool-use" "$P/.claude/settings.json")
[ "$count" -eq 1 ] && ok "harness hooks not duplicated" || bad "harness hooks not duplicated ($count)"
contains "lock records the new version" "99.0.0-test" "$(cat "$P/backbone/.harness-lock.json")"
expect 0 "second update is clean" "$H2/update.sh" "$P"
expect 0 "--force takes the harness version" "$H2/update.sh" "$P" --force
contains "--force replaced the local edit" "Upstream workflow change." "$(cat "$P/backbone/8-WORKFLOW.md")"

section "install over an existing project"
E="$WORK/existing"
new_repo "$E"
mkdir -p "$E/.claude" "$E/backbone"
echo "# my own agent rules" > "$E/AGENTS.md"
echo "# existing tasks" > "$E/backbone/3-TASKS.md"
echo '{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]}}' > "$E/.claude/settings.json"
git -C "$E" config core.hooksPath .husky
expect 1 "existing AGENTS.md becomes a conflict" "$HARNESS/bootstrap.sh" "$E"
contains "existing AGENTS.md kept" "my own agent rules" "$(cat "$E/AGENTS.md")"
contains "existing tasks kept" "existing tasks" "$(cat "$E/backbone/3-TASKS.md")"
contains "existing Stop hook kept" "echo mine" "$(cat "$E/.claude/settings.json")"
contains "foreign core.hooksPath respected" ".husky" "$(git -C "$E" config core.hooksPath)"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
