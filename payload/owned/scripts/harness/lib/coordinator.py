#!/usr/bin/env python3
"""Agentic harness: Orca coordinator (harness-owned). Run it as `python3 scripts/harness/lib/harness.py orca`.

Drives ready tasks through the pipeline with Orca supervised workers, one worker per step:

  - asks the harness what each task needs (`harness.py next <id> --json`), so it never re-implements the workflow;
  - starts a worker for each role step (analyst, architect, griller, tester, implementer, judge, debugger, scribe),
    and runs the command steps itself (approve, start, finish and the commit), all through the harness gates;
  - answers a worker's question by starting an analyst or architect worker. The answer goes into the spec (with its
    source), and the reply tells the asking worker where to find it. A question nobody can answer is escalated;
  - parks a task when the harness parks it (BLOCKED), and reports every task's outcome and the open escalations.

Each task runs in its own git worktree on branch harness/task-<id>, so tasks run in parallel without sharing
3-TASKS.md. Orca workers can't inherit environment variables, so a worker is an orchestrator session for one step:
it delegates the step to the role agent, and the hooks hold that agent to its role.

Orca's lifecycle rules are followed strictly: every delivery is acknowledged after it is processed, a worker is
released only after it settled, and nothing is stopped, abandoned or retried without proof. When the state is
unclear the coordinator stops and reports instead of guessing.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

ROLE_STEPS = ("define", "grill", "answer", "test", "implement", "judge", "diagnose", "fix", "finish")
COMMAND_STEPS = ("approve", "start")
END_STEPS = ("blocked", "done", "unknown")
WAIT_TYPES = "worker_done,escalation,question,heartbeat"   # heartbeats are only acknowledged

INSTRUCTIONS = {
    "define": "Write or complete the spec backbone/specs/{task}.md for this task: {detail}",
    "grill": "Grill the spec backbone/specs/{task}.md. The harness records the griller's verdict.",
    "answer": "Answer the griller's open questions on backbone/specs/{task}.md from backbone/ and, when it is on, the "
              "knowledge source. Record each answer under Assumptions with its source; leave what the sources don't "
              "settle as an open question and escalate it. The questions: {detail}",
    "test": "Write the acceptance tests for task {task} from its approved spec (HARNESS_ACCEPTANCE_PATHS). The "
            "harness records them.",
    "implement": "Implement task {task} from its approved spec, loading the skills it needs.",
    "judge": "Judge task {task} against its spec. The harness records the judge's verdict.",
    "diagnose": "Diagnose why the judge failed task {task} and write the fix brief. The harness records it.",
    "fix": "Fix what the judge found in task {task}. The judge's findings and the debugger's brief: {detail}",
    "finish": "Record what task {task} taught (lessons, traps, emergent decisions) in backbone/.",
}

WORKER_SPEC = """Harness step for task {task} ("{title}"): {step}.

Target: this repository's task {task} (spec: backbone/specs/{task}.md).
Change: {instruction}
Ownership: you orchestrate; delegate the work to the `{role}` agent (Claude Code: the Task tool with subagent_type
"{role}"; Codex: spawn the custom agent "{role}"; OpenCode: the subagent tool with agent "{role}"). The harness hooks
hold that agent to its role and refuse what the gates don't allow: never work around a refusal.
Constraints: follow AGENTS.md. Do only this step. Don't start other tasks, don't mark the task [x] and don't commit;
the coordinator does that. If you need an answer that backbone/ and the knowledge source don't give, ask the
coordinator (orca orchestration ask) instead of guessing. If a human must decide, run
python3 scripts/harness/lib/harness.py escalate {task} --reason "<what and why>" and report it.
Observable acceptance: `python3 scripts/harness/lib/harness.py next {task}` no longer says "{step}"{role_note}.
Report with worker_done: --outcome succeeded when the step is done, failed when it couldn't be."""

ANSWER_SPEC = """Harness question for task {task} ("{title}") from the {asker} worker.

The question: {question}

Target: backbone/specs/{task}.md.
Change: have the `{role}` agent answer it from backbone/ and, when it is on, the read-only knowledge source. A clear
answer goes into the spec under Assumptions with its source (`backbone/...` or `vault:<path>`). If the sources don't
settle it clearly, don't guess: run python3 scripts/harness/lib/harness.py escalate {task} --reason "<the question>".
Ownership: delegate to the `{role}` agent (Claude Code: Task tool, subagent_type "{role}"; Codex: the custom agent
"{role}"; OpenCode: the subagent tool). Only the spec may change.
Observable acceptance: the answer is in the spec with its source, or the task is escalated.
Report with worker_done: start the summary with "ANSWER:" and the answer plus the assumption id, or with
"ESCALATED:" when you escalated."""


class CoordinatorError(Exception):
    pass


def find(value, *keys):
    """The first non-empty value under any of keys, anywhere in a JSON value."""
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, "", [], {}):
                return value[key]
        for item in value.values():
            found = find(item, *keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value:
            found = find(item, *keys)
            if found not in (None, "", [], {}):
                return found
    return None


def payload_of(message):
    payload = message.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    return payload if isinstance(payload, dict) else {}


class Orca(object):
    """The orca CLI, JSON in and out."""

    def __init__(self, binary, cwd):
        self.binary = binary
        self.cwd = cwd

    def __call__(self, *args, timeout=120):
        argv = [self.binary] + list(args) + ["--json"]
        try:
            result = subprocess.run(argv, cwd=str(self.cwd), capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CoordinatorError("orca %s: %s" % (" ".join(args[:2]), exc))
        try:
            data = json.loads(result.stdout or "{}")
        except ValueError:
            raise CoordinatorError("orca %s printed no JSON: %s" % (" ".join(args[:2]), (result.stderr or result.stdout)[:300]))
        if data.get("ok") is False:
            error = data.get("error") or {}
            raise CoordinatorError("orca %s: %s (%s)" % (" ".join(args[:2]), error.get("message"), error.get("code")))
        return data.get("result", data)


class Coordinator(object):
    def __init__(self, root, opts, log=print):
        self.root = Path(root)
        self.opts = opts
        self.log = log
        self.orca = Orca(opts.get("orca") or shutil.which("orca") or "orca", self.root)
        self.agents = opts.get("agents") or {}
        self.launch = opts.get("launch") or {}   # agent -> command to start it with (Codex: the hook-trust bypass)
        self.tasks = {}          # task -> {"path", "branch", "title", "steps": [...], "outcome"}
        self.active = {}         # dispatch id -> {"task", "step", "role", "kind": "step"|"answer", ...}
        self.delivery = None
        self.run = opts.get("run")

    # ----------------------------------------------------------------- harness in a task's worktree

    def harness(self, path, *args, check=False):
        result = subprocess.run(["python3", str(Path(path) / "scripts/harness/lib/harness.py")] + list(args),
                                cwd=str(path), capture_output=True, text=True, timeout=1800)
        if check and result.returncode != 0:
            raise CoordinatorError("harness %s: %s" % (" ".join(args), (result.stdout + result.stderr).strip()[:500]))
        return result

    def next_step(self, task):
        result = self.harness(self.tasks[task]["path"], "next", task, "--json")
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise CoordinatorError("harness next %s printed no JSON: %s" % (task, result.stderr.strip()[:300]))

    def git(self, path, *args):
        return subprocess.run(["git"] + list(args), cwd=str(path), capture_output=True, text=True)

    # ----------------------------------------------------------------- workspaces

    def ensure_repo(self):
        """Orca supervises workers only in folders it knows: register the repository (once)."""
        try:
            self.orca("repo", "add", "--path", str(self.root))
        except CoordinatorError as exc:
            if "exist" not in str(exc).lower() and "already" not in str(exc).lower():
                raise

    def workspace(self, task):
        """(path, branch, selector) of task's Orca worktree, created on the current branch if missing."""
        base = self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if self.opts.get("here"):
            return self.root, base, "path:%s" % self.root
        name = "harness-task-%s" % re.sub(r"[^A-Za-z0-9._-]", "-", task)
        listed = self.orca("worktree", "list", "--repo", "path:%s" % self.root)
        rows = find(listed, "worktrees") or (listed if isinstance(listed, list) else [])
        tree = next((w for w in rows if isinstance(w, dict) and w.get("displayName") == name
                     and not w.get("isArchived")), None)
        if tree is None:
            created = self.orca("worktree", "create", "--name", name, "--repo", "path:%s" % self.root,
                                "--base-branch", base, "--setup", "skip", "--no-parent", timeout=300)
            tree = find(created, "worktree") or created
        path, branch = tree.get("path"), str(tree.get("branch") or name).replace("refs/heads/", "")
        if not path or not tree.get("id"):
            raise CoordinatorError("orca worktree for task %s has no path or id: %s" % (task, json.dumps(tree)[:300]))
        return Path(path), branch, "id:%s" % tree["id"]

    def trust(self, path):
        """--trust: mark a task worktree trusted for Claude Code and Codex, so a worker isn't stopped by a trust
        dialog (Orca reports it as "Agent startup blocked: agent-trust-workspace")."""
        self.trust_codex(path)
        config = Path(os.path.expanduser("~/.claude.json"))
        try:
            data = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        except ValueError:
            raise CoordinatorError("~/.claude.json is not valid JSON; not touching it")
        entry = data.setdefault("projects", {}).setdefault(os.path.realpath(str(path)), {})
        if entry.get("hasTrustDialogAccepted") is not True:
            entry["hasTrustDialogAccepted"] = True
            tmp = config.with_name(config.name + ".harness-tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(config))
            self.log("orca: trusted %s for Claude Code (--trust)" % path)

    def trust_codex(self, path):
        config = Path(os.path.expanduser("~/.codex/config.toml"))
        if not config.parent.is_dir():
            return
        header = '[projects."%s"]' % os.path.realpath(str(path))
        text = config.read_text(encoding="utf-8") if config.exists() else ""
        if header in text:
            return
        with config.open("a", encoding="utf-8") as handle:
            handle.write('%s%s\ntrust_level = "trusted"\n' % ("\n" if text and not text.endswith("\n\n") else "", header))
        self.log("orca: trusted %s for Codex (--trust)" % path)

    def waiting_for_approval(self):
        """Log (once per worker) a worker whose agent waits at a permission prompt in its terminal. The coordinator
        never answers it: approving commands is the user's call."""
        for dispatch, entry in self.active.items():
            if entry.get("prompt_logged") or not entry.get("handle"):
                continue
            try:
                shown = self.orca("terminal", "read", "--terminal", entry["handle"])
            except CoordinatorError:
                continue
            tail = find(shown, "tail") or []
            text = "\n".join(tail[-14:]) if isinstance(tail, list) else str(tail)
            if re.search(r"(?i)would you like to run|do you want to (proceed|allow)|allow this (command|action)", text):
                command = next((line.strip() for line in reversed(tail) if line.strip().startswith("$ ")), "")
                entry["prompt_logged"] = True
                self.log("orca: task %s: the %s worker (%s) waits for an approval in its terminal: %s. Approve it "
                         "there; to stop Orca's own commands from asking each time, see backbone/HOOKS.md (Orca "
                         "coordinator)." % (entry["task"], entry["role"], self.agent_for(entry["role"]), command[:160]))

    def failed_workers(self):
        """Active dispatches Orca itself reports as ended without a worker_done (for example a blocked startup)."""
        failed = []
        for dispatch in list(self.active):
            try:
                shown = self.orca("orchestration", "worker-show", "--dispatch", dispatch)
            except CoordinatorError:
                continue
            status = str(find(shown, "status") or "").lower()
            if status in ("failed", "abandoned", "stopped", "cancelled"):
                failed.append((dispatch, find(shown, "lastFailure", "terminationReason") or status))
        return failed

    # ----------------------------------------------------------------- workers

    def agent_for(self, role):
        return self.agents.get(role) or self.agents.get("default") or "claude"

    def start_worker(self, task, spec, role, kind, extra=None):
        info = self.tasks[task]
        agent = self.agent_for(role)
        args = ["orchestration", "worker-start", "--spec", spec, "--worktree", info["selector"],
                "--task-title", "%s %s: %s" % (kind, task, role)]
        launched = None
        if self.launch.get(agent):
            # Orca's own launch can't add flags; open the agent in a terminal with its command, then supervise it.
            command = self.launch[agent]
            if agent == "codex":
                # A worktree's git metadata lives in the main repository's .git, outside the worktree: let Codex's
                # workspace-write sandbox write there too, or every git and harness command asks for approval.
                common = self.git(info["path"], "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
                if common:
                    command += " -c %s" % shlex.quote('sandbox_workspace_write.writable_roots=["%s"]' % common)
            terminal = self.orca("terminal", "create", "--worktree", info["selector"], "--title",
                                 "harness %s %s" % (task, role), "--command", command)
            handle = find(terminal, "handle", "terminalHandle", "terminal_handle")
            if not handle:
                raise CoordinatorError("terminal create for %s returned no handle: %s" % (agent, json.dumps(terminal)[:300]))
            time.sleep(self.opts.get("launch_wait", 8))
            args += ["--terminal", handle]
            launched = handle
        else:
            args += ["--agent", agent]
        if self.run:
            args += ["--run", self.run]
        receipt = self.orca(*args, timeout=600)
        dispatch = find(receipt, "dispatchId", "dispatch_id")
        if not dispatch:
            raise CoordinatorError("worker-start for task %s returned no dispatch id: %s" % (task, json.dumps(receipt)[:300]))
        entry = {"task": task, "role": role, "kind": kind, "started": time.time(),
                 "handle": find(receipt, "terminalHandle", "terminal_handle", "agentTerminalHandle", "handle") or launched}
        entry.update(extra or {})
        self.active[dispatch] = entry
        self.log("orca: task %s: %s worker (%s, %s) started: %s" % (task, role, kind, agent, dispatch))
        return dispatch

    def release(self, dispatch):
        try:
            self.orca("orchestration", "worker-release", "--dispatch", dispatch)
        except CoordinatorError as exc:
            self.log("orca: release of %s left for you: %s" % (dispatch, exc))

    # ----------------------------------------------------------------- the step loop

    def advance(self, task):
        """Run command steps and start the next role worker for task; False when the task is settled."""
        info = self.tasks[task]
        for _ in range(12):
            step = self.next_step(task)
            name = step.get("step")
            key = (name, step.get("role"))
            info["steps"].append(key)
            if info["steps"].count(key) > self.opts.get("max_repeats", 3):
                self.harness(info["path"], "escalate", task, "--kind", "coordinator", "--reason",
                             "the %s step came back %d times without progress" % (name, info["steps"].count(key)),
                             "--needed", "a look at the task's verdicts and the workers' transcripts")
                info["outcome"] = "escalated (no progress at %s)" % name
                return False
            if name == "done" and self.opts.get("merge") and not self.opts.get("here") and task not in self.base_done():
                # Finished on its branch in an earlier run but never reached the base (a merge that was refused, a
                # run that stopped): merge it now, so the tasks after it can start.
                info["outcome"] = "done"
                self.log("orca: task %s: done on its branch, not yet on the base; merging" % task)
                return self.merge(task)
            if name in END_STEPS:
                info["outcome"] = name
                self.log("orca: task %s: %s%s" % (task, name, (": " + "; ".join(step.get("escalations") or []))[:300]
                                                  if step.get("escalations") else ""))
                return False
            if name in ("approve", "start") and not info.get("synced"):
                info["synced"] = True
                self.sync(task)
                continue
            if name == "approve":
                if not step.get("command"):
                    info["outcome"] = "waiting for the user's approval"
                    return False
                self.log("orca: task %s: approve" % task)
                approved = self.harness(info["path"], "approve", task)
                if approved.returncode != 0 and self.next_step(task).get("step") == "approve":
                    # Refused without escalating (approve escalates risky specs itself): say why and park it,
                    # rather than asking again and again.
                    why = (approved.stdout + approved.stderr).strip()
                    self.log("orca: task %s: approve refused: %s" % (task, why[:400]))
                    self.harness(info["path"], "escalate", task, "--kind", "approval", "--reason",
                                 "policy approval refused the spec: %s" % why[:800],
                                 "--needed", "the spec fixed (or the user's Approved-by: line)")
                    info["outcome"] = "escalated (approve refused)"
                    return False
                continue
            if name == "start":
                self.log("orca: task %s: start" % task)
                self.harness(info["path"], "start", task, check=True)
                continue
            if name == "answer" and len(step.get("roles") or []) > 1:
                # Every role answers its questions before the griller looks again (an edit re-triggers the grill).
                info["answer_queue"] = [(r, [q for q in step.get("questions") or [] if q.get("route") == r])
                                        for r in step["roles"][1:]]
                step = dict(step, role=step["roles"][0],
                            questions=[q for q in step.get("questions") or [] if q.get("route") == step["roles"][0]])
            if name in ROLE_STEPS and step.get("role"):
                detail = json.dumps(step.get("questions") or step.get("problems") or step.get("brief")
                                    or step.get("findings") or step.get("reason") or "", ensure_ascii=False)[:4000]
                spec = WORKER_SPEC.format(task=task, title=info["title"], step=name, role=step["role"],
                                          instruction=INSTRUCTIONS[name].format(task=task, detail=detail),
                                          role_note=" (for the finish step: the scribe has recorded the task)"
                                          if name == "finish" else "")
                self.start_worker(task, spec, step["role"], "step", {"step": name})
                return True
            info["outcome"] = "stopped at an unknown step: %s" % name
            return False
        info["outcome"] = "stopped: too many command steps in a row"
        return False

    def finish(self, task):
        """After the scribe: mark the task [x] through the judge gate and commit it; optionally open a PR."""
        info = self.tasks[task]
        done = self.harness(info["path"], "finish", task)
        if done.returncode != 0:
            info["outcome"] = "finish refused: %s" % done.stdout.strip()[:300]
            return False
        self.git(info["path"], "add", "-A")
        subject = ("feat: task %s: %s" % (task, info["title"]))[:72]
        commit = self.git(info["path"], "commit", "-q", "-m", subject)
        if commit.returncode != 0:
            info["outcome"] = "done, but the commit was refused: %s" % (commit.stderr + commit.stdout).strip()[:400]
            return False
        info["outcome"] = "done"
        if self.opts.get("merge") and not self.opts.get("here"):
            self.merge(task)
        if self.opts.get("pr") and not self.opts.get("here"):
            pushed = self.git(info["path"], "push", "-q", "-u", "origin", info["branch"])
            if pushed.returncode == 0 and shutil.which("gh"):
                pr = subprocess.run(["gh", "pr", "create", "--head", info["branch"], "--title", subject, "--body",
                                     "Opened by the harness Orca coordinator: task %s passed the judge and the gates."
                                     % task], cwd=str(info["path"]), capture_output=True, text=True)
                info["pr"] = (pr.stdout or pr.stderr).strip()
        return True

    def on_done(self, dispatch, message):
        entry = self.active.pop(dispatch)
        task = entry["task"]
        outcome = str(find(payload_of(message), "outcome") or "").lower()
        summary = (message.get("body") or "").strip()
        self.release(dispatch)
        if entry["kind"] == "answer":
            answer = summary if summary else "The answer worker reported nothing."
            if outcome == "failed" or answer.upper().startswith("ESCALATED"):
                answer = ("Nobody could answer this from the sources; it is escalated to the user. Finish what doesn't "
                          "depend on it, then report the step as failed.\n" + answer)
            self.orca("orchestration", "reply", "--id", entry["question"], "--body", answer[:4000])
            self.log("orca: task %s: answered question %s" % (task, entry["question"]))
            return
        self.log("orca: task %s: %s worker finished (%s)%s" % (task, entry["role"], outcome or "no outcome",
                                                              ": " + summary[:200] if outcome == "failed" else ""))
        if entry.get("step") == "finish":
            self.finish(task)
            self.start_next()
            return
        if entry.get("step") == "integrate":
            info = self.tasks[task]
            if not self.finish_integration(task, info.get("integrate_message") or "chore: integrate task %s" % task):
                self.start_next()
            return
        queue = self.tasks[task].get("answer_queue") or []
        if entry.get("step") == "answer" and queue:
            role, questions = queue.pop(0)
            spec = WORKER_SPEC.format(task=task, title=self.tasks[task]["title"], step="answer", role=role,
                                      instruction=INSTRUCTIONS["answer"].format(
                                          task=task, detail=json.dumps(questions, ensure_ascii=False)[:4000]),
                                      role_note="")
            self.start_worker(task, spec, role, "step", {"step": "answer"})
            return
        if not self.advance(task):
            self.start_next()

    def on_question(self, message):
        asker = next((d for d, e in self.active.items() if e.get("handle") == message.get("from_handle")), None)
        task = self.active[asker]["task"] if asker else None
        if task is None:
            self.orca("orchestration", "reply", "--id", message["id"], "--body",
                      "The coordinator couldn't tell which task this is for. Escalate it with harness.py escalate.")
            return
        question = message.get("body") or message.get("subject") or ""
        role = "architect" if re.search(r"(?i)\b(ADR|architecture|design|module|layer|interface)", question) \
            else "analyst"
        spec = ANSWER_SPEC.format(task=task, title=self.tasks[task]["title"], asker=self.active[asker]["role"],
                                  question=question, role=role)
        self.start_worker(task, spec, role, "answer", {"question": message["id"]})

    # ----------------------------------------------------------------- main loop

    def drive(self, task_ids):
        if not self.run:
            created = self.orca("orchestration", "run-create", "--objective",
                                "agentic harness: tasks %s" % ", ".join(task_ids))
            self.run = find(created, "id")
            self.log("orca: run %s" % self.run)
        self.ensure_repo()
        if self.opts.get("trust"):
            # Claude Code decides trust for a git worktree by its main repository, so trust that too.
            self.trust(self.root)
        self.queue = list(task_ids)
        self.start_next()
        empty = 0
        deadline = time.time() + self.opts.get("timeout", 4 * 3600)
        while self.active and time.time() < deadline:
            if Path(self.root / ".git" / "harness" / "STOP").exists():
                self.log("orca: halted by .git/harness/STOP; workers already running are left to settle")
                break
            args = ["orchestration", "check", "--run", self.run, "--wait", "--types", WAIT_TYPES,
                    "--timeout-ms", str(self.opts.get("wait_ms", 900000))]
            if self.delivery:
                args += ["--ack", self.delivery]
            batch = self.orca(*args, timeout=self.opts.get("wait_ms", 900000) / 1000 + 120)
            self.delivery = batch.get("deliveryId")
            messages = batch.get("messages") or []
            empty = 0 if messages else empty + 1
            if not messages:
                self.waiting_for_approval()
            if empty >= 3:
                self.log("orca: no messages after 3 waits; %d worker(s) still active: %s. Check them with "
                         "orca orchestration worker-list --run %s" % (len(self.active), ", ".join(self.active), self.run))
                empty = 0
            for message in messages:
                kind = message.get("type")
                dispatch = find(payload_of(message), "dispatchId", "dispatch_id") or next(
                    (d for d, e in self.active.items() if e.get("handle") == message.get("from_handle")), None)
                if kind == "worker_done" and dispatch in self.active:
                    self.on_done(dispatch, message)
                elif kind == "question":
                    self.on_question(message)
                elif kind == "escalation" and dispatch in self.active:
                    self.log("orca: task %s escalated: %s" % (self.active[dispatch]["task"], message.get("subject")))
            # After the mailbox: a worker that reported has settled already; these ended without a report.
            for dispatch, why in self.failed_workers():
                entry = self.active.pop(dispatch)
                self.release(dispatch)
                task = entry["task"]
                self.log("orca: task %s: the %s worker failed before reporting: %s" % (task, entry["role"], why))
                self.harness(self.tasks[task]["path"], "escalate", task, "--kind", "coordinator", "--reason",
                             "the %s worker (%s) failed: %s" % (entry["role"], self.agent_for(entry["role"]), why),
                             "--needed", "a look at that agent in this worktree (trust, login, configuration)")
                self.tasks[task]["outcome"] = "escalated (%s worker failed: %s)" % (entry["role"], why)
            self.start_next()
        if self.delivery:
            try:
                self.orca("orchestration", "check", "--run", self.run, "--ack", self.delivery, "--peek")
            except CoordinatorError:
                pass
        return self.report()

    def base_done(self):
        """Tasks marked [x] on the base branch (the root checkout), where --merge brings finished tasks."""
        state = self.harness(self.root, "state", "--json")
        try:
            return {t["task"] for t in json.loads(state.stdout or "{}").get("tasks", []) if t.get("state") == "done"}
        except ValueError:
            return set()

    def start_next(self):
        """Fill the free slots (--parallel) with queued tasks whose dependencies (after: ...) are done on the base."""
        while self.queue:
            running = [t for t, i in self.tasks.items() if i["outcome"] is None]
            if len(running) >= self.opts.get("parallel", 2):
                return
            done = self.base_done()
            deps = self.opts.get("deps") or {}
            ready = next((t for t in self.queue if set(deps.get(t, [])) <= done), None)
            if ready is None:
                if not running:
                    for task in self.queue:
                        self.tasks[task] = {"path": self.root, "branch": "", "selector": "", "title": "", "steps": [],
                                            "outcome": "waiting for %s" % ", ".join(sorted(set(deps.get(task, [])) - done))}
                    self.queue = []
                return
            self.queue.remove(ready)
            path, branch, selector = self.workspace(ready)
            if self.opts.get("trust"):
                self.trust(path)
            state = self.harness(path, "state", "--json")
            titles = {t["task"]: t["title"] for t in json.loads(state.stdout or "{}").get("tasks", [])}
            self.tasks[ready] = {"path": path, "branch": branch, "selector": selector, "title": titles.get(ready, ""),
                                 "steps": [], "outcome": None}
            self.advance(ready)

    def harness_owned(self):
        """The base's harness-owned files (its lock lists them): a task never decides their version."""
        try:
            lock = json.loads((self.root / "backbone/.harness-lock.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lock = {}
        return set(lock.get("files") or {}) | {"backbone/.harness-lock.json"}

    def merge(self, task):
        """--merge: bring a finished task's branch into the base branch, so the tasks after it build on it. Returns
        True when an integration worker was started (the task's code conflicts with what the base has gained)."""
        info = self.tasks[task]
        if self.git(self.root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
            info["outcome"] += "; not merged: the base checkout has uncommitted changes"
            return False
        self.renumber_adrs(task)
        message = "chore: merge task %s (%s)" % (task, info["branch"])
        merged = self.git(self.root, "merge", "--no-ff", "-m", message, info["branch"])
        if merged.returncode != 0:
            remaining = self.resolve_conflicts(self.root, task, base_stage=2)
            if remaining:
                self.git(self.root, "merge", "--abort")
                base_head = self.git(self.root, "rev-parse", "HEAD").stdout.strip()
                # Integrate again while the base keeps moving (other tasks merged in meanwhile), up to 3 times.
                if info.get("integrated_at") != base_head and info.get("integrations", 0) < 3:
                    return self.integrate(task)
                info["outcome"] += "; not merged: code conflicts remain in %s" % ", ".join(remaining[:5])
                return False
            if not self.commit_merge(self.root, message):
                self.git(self.root, "merge", "--abort")
                info["outcome"] += "; not merged: the merge commit was refused"
                return False
            self.log("orca: task %s: resolved the backbone and harness conflicts" % task)
        info["outcome"] += "; merged into %s" % self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        self.log("orca: task %s merged" % task)
        return False

    def sync(self, task):
        """Bring a task's branch up to date with the base before it is approved: decisions taken on the base since
        the worktree was made (accepted ADRs, answered questions, other tasks' code) apply to it, and later merges
        conflict less. Only conflicts the harness understands are resolved; with a code conflict the branch stays as
        it is, and the integrate step deals with it at merge time."""
        if self.opts.get("here"):
            return
        info = self.tasks[task]
        base = self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        behind = self.git(info["path"], "rev-list", "--count", "HEAD..%s" % base).stdout.strip()
        if not behind or behind == "0" or self.git(info["path"], "status", "--porcelain", "--untracked-files=no").stdout.strip():
            return
        merged = self.git(info["path"], "merge", "--no-ff", "--no-commit", base)
        if merged.returncode != 0 and self.resolve_conflicts(info["path"], task, base_stage=3):
            self.git(info["path"], "merge", "--abort")
            self.log("orca: task %s: not synced with %s (code conflicts; integrated at merge time)" % (task, base))
            return
        if self.git(info["path"], "diff", "--cached", "--quiet").returncode != 0 or merged.returncode != 0:
            self.commit_merge(info["path"], "chore: sync task %s with %s" % (task, base))
        self.harness(info["path"], "snapshot")
        self.log("orca: task %s: synced with %s (%s commit(s))" % (task, base, behind))

    def renumber_adrs(self, task):
        """Give the branch's new ADRs numbers the base doesn't already use for another ADR (tasks numbered in
        parallel), updating the references in the files the branch changed. Committed on the task's branch."""
        info = self.tasks[task]
        base = self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        added = [n for n in self.git(info["path"], "diff", "--name-only", "--diff-filter=A", "%s...HEAD" % base,
                                     "--", "backbone/adr/").stdout.splitlines() if re.match(r"backbone/adr/ADR-\d+", n)]
        base_files = [n for n in self.git(self.root, "ls-files", "backbone/adr/").stdout.splitlines()]
        changed = [n for n in self.git(info["path"], "diff", "--name-only", "%s...HEAD" % base).stdout.splitlines() if n]
        renamed = []
        for name in added:
            number = re.match(r"backbone/adr/ADR-(\d+)", name).group(1)
            clash = [b for b in base_files if re.match(r"backbone/adr/ADR-%s\b" % number, b) and b != name]
            if not clash:
                continue
            new_id = self.harness(info["path"], "adr-number").stdout.strip()
            old_id = "ADR-%s" % number
            new_name = name.replace(old_id, new_id, 1)
            self.git(info["path"], "mv", name, new_name)
            for path in set(changed + [new_name]) - {name}:
                full = info["path"] / path
                if full.is_file():
                    try:
                        text = full.read_text(encoding="utf-8")
                    except (UnicodeDecodeError, OSError):
                        continue   # binary files don't name ADRs
                    updated = re.sub(r"\b%s\b" % old_id, new_id, text)
                    if updated != text:
                        full.write_text(updated, encoding="utf-8")
            renamed.append("%s -> %s" % (old_id, new_id))
        if renamed:
            self.git(info["path"], "add", "-A")
            self.commit_merge(info["path"], "chore(adr): renumber %s (taken on %s)" % (", ".join(renamed), base))
            self.harness(info["path"], "snapshot")
            self.log("orca: task %s: renumbered %s (another task took the number)" % (task, ", ".join(renamed)))

    def integrate(self, task):
        """The task's code conflicts with what the base gained meanwhile (parallel tasks built the same module).
        Merge the base into the task's branch in its worktree, resolve what the harness can, and hand the remaining
        code conflicts to an implementer worker; the result must pass the tests before the task is merged."""
        info = self.tasks[task]
        info["integrations"] = info.get("integrations", 0) + 1
        info["integrated_at"] = self.git(self.root, "rev-parse", "HEAD").stdout.strip()
        base = self.git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        message = "chore: merge %s into task %s" % (base, task)
        self.git(info["path"], "merge", "--no-ff", "--no-commit", base)
        remaining = self.resolve_conflicts(info["path"], task, base_stage=3)
        self.harness(info["path"], "snapshot")
        if not remaining:
            return self.finish_integration(task, message)
        info["outcome"], info["integrate_message"], info["conflicts"] = None, message, remaining
        self.log("orca: task %s: code conflicts with %s in %s; an implementer integrates them"
                 % (task, base, ", ".join(remaining[:5])))
        spec = WORKER_SPEC.format(
            task=task, title=info["title"], step="integrate", role="implementer", role_note="",
            instruction=("This task is done, but its branch now conflicts with %s, which gained other tasks' work in "
                         "the same files. A merge is in progress in this worktree. Resolve the conflict markers in "
                         "these files only: %s. Keep both sides' behaviour, this task's and the base's (each side's "
                         "tests must keep passing). Edit them with your file tools; don't run git, don't commit and "
                         "don't touch other files. Then run the test command (backbone/harness.conf, HARNESS_TEST_CMD)."
                         % (base, ", ".join(remaining))))
        spec = spec.replace('`python3 scripts/harness/lib/harness.py next %s` no longer says "integrate"' % task,
                            "no conflict markers are left in those files and the tests pass")
        self.start_worker(task, spec, "implementer", "step", {"step": "integrate"})
        return True

    def finish_integration(self, task, message):
        info = self.tasks[task]
        left = [f for f in info.get("conflicts") or []
                if (info["path"] / f).exists() and "<<<<<<<" in (info["path"] / f).read_text(encoding="utf-8",
                                                                                          errors="replace")]
        if left:
            self.git(info["path"], "merge", "--abort")
            self.escalate_integration(task, "conflict markers are still in %s" % ", ".join(left[:5]))
            return False
        self.git(info["path"], "add", "-A")
        if not self.commit_merge(info["path"], message):
            self.git(info["path"], "merge", "--abort")
            self.escalate_integration(task, "the integration commit was refused")
            return False
        self.harness(info["path"], "snapshot")
        tests = self.harness(info["path"], "test-run")
        if tests.returncode != 0:
            self.escalate_integration(task, "the tests fail after integrating: %s" % tests.stdout.strip()[:300])
            return False
        self.log("orca: task %s: integrated with the base; the tests pass" % task)
        info["outcome"] = "done"
        return self.merge(task)

    def escalate_integration(self, task, why):
        info = self.tasks[task]
        self.harness(info["path"], "escalate", task, "--kind", "integration", "--reason",
                     "task %s is done but can't be merged: %s" % (task, why),
                     "--needed", "a person to integrate the task's branch with the base")
        info["outcome"] = "done; not merged: %s (escalated)" % why

    def commit_merge(self, cwd, message):
        # The gates passed on each task's own commit; a merge commit puts several tasks' code together, so a judge
        # fingerprint can't match it. A clean merge doesn't run the pre-commit hook; this one skips verify likewise.
        committed = subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(cwd), capture_output=True,
                                   text=True, env=dict(os.environ, HARNESS_VERIFY="off"))
        return committed.returncode == 0

    LOGS = ("backbone/6-MEMORY.md", "backbone/5-DECISIONS.md")
    ESCALATIONS = "backbone/escalations.md"

    @staticmethod
    def merge_escalations(ours, theirs):
        """Both sides' escalation entries, by heading, in order; an entry resolved on either side stays resolved."""
        def split(text):
            head, _, rest = text.partition("\n## ")
            parts = ("## " + rest).split("\n## ") if rest else []
            return head, ["## " + p if not p.startswith("## ") else p for p in parts]
        head, mine = split(ours)
        _, other = split(theirs)
        entries, order = {}, []
        for entry in mine + other:
            key = entry.splitlines()[0].strip()
            if key not in entries:
                order.append(key)
                entries[key] = entry
            elif "Status: open" in entries[key] and "Status: open" not in entry:
                entries[key] = entry
        return head.rstrip("\n") + "\n\n" + "\n".join(e.rstrip("\n") + "\n" for e in (entries[k] for k in order))

    def resolve_conflicts(self, cwd, task, base_stage):
        """Resolve the conflicts the harness understands, in checkout cwd: harness-owned files take the base's
        version; 3-TASKS.md takes the base's list with this task marked [x]; the memory and decision logs keep both
        sides; escalations.md is merged by entry. Returns the conflicted files left over (code). base_stage is git's
        stage of the base side: 2 when merging into the base, 3 when merging the base into the task's branch."""
        cwd = Path(cwd)
        conflicted = [n for n in self.git(cwd, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if n]
        task_stage = 5 - base_stage
        owned = self.harness_owned()
        git_dir = Path(self.git(cwd, "rev-parse", "--absolute-git-dir").stdout.strip())
        remaining = []
        for name in conflicted:
            path = cwd / name
            show = lambda stage, name=name: self.git(cwd, "show", ":%d:%s" % (stage, name)).stdout
            if name in owned:
                self.git(cwd, "checkout", "--ours" if base_stage == 2 else "--theirs", "--", name)
            elif name == "backbone/3-TASKS.md":
                path.write_text(re.sub(r"(?m)^(\s*[-*]\s+)\[[^\]]*\](\s*\**Task %s\b)" % re.escape(task), r"\1[x]\2",
                                       show(base_stage), count=1), encoding="utf-8")
            elif name == self.ESCALATIONS:
                path.write_text(self.merge_escalations(show(base_stage), show(task_stage)), encoding="utf-8")
            elif name in self.LOGS:
                stages = {}
                for stage in (1, 2, 3):
                    tmp = git_dir / ("harness-merge-%d" % stage)
                    tmp.write_text(show(stage), encoding="utf-8")
                    stages[stage] = tmp
                subprocess.run(["git", "merge-file", "--union", str(stages[2]), str(stages[1]), str(stages[3])],
                               cwd=str(cwd), capture_output=True)
                path.write_text(stages[2].read_text(encoding="utf-8"), encoding="utf-8")
                for tmp in stages.values():
                    tmp.unlink()
            else:
                remaining.append(name)
                continue
            self.git(cwd, "add", name)
        return remaining

    def report(self):
        lines = ["harness orca: run %s" % self.run]
        for task, info in self.tasks.items():
            state = info["outcome"] or ("in progress (%s)" % ", ".join(
                e["role"] for e in self.active.values() if e["task"] == task) or "unknown")
            lines.append("  task %s: %s%s" % (task, state, ("  " + info["pr"]) if info.get("pr") else ""))
        proposed = []
        for adr in sorted((self.root / "backbone" / "adr").glob("ADR-*.md")):
            text = adr.read_text(encoding="utf-8", errors="replace")
            status = re.search(r"(?m)^## Status\s*\n+\s*(\S+)", text)
            if status and status.group(1).lower().startswith("proposed"):
                proposed.append(adr.stem)
        if proposed:
            lines.append("ADRs on the base waiting for your acceptance: %s" % ", ".join(proposed))
        escalations = []
        for task, info in self.tasks.items():
            out = [line for line in self.harness(info["path"], "escalations").stdout.splitlines()
                   if line.startswith("open ")]
            escalations.extend("  [%s] %s" % (task, line[5:].strip()) for line in out)
        if escalations:
            lines.append("Open escalations (answer them, then run harness.py orca again):")
            lines.extend(escalations)
        text = "\n".join(lines)
        self.log(text)
        return 0 if all((i["outcome"] or "").startswith(("done", "blocked", "escalated", "waiting"))
                        for i in self.tasks.values()) and not self.active else 1
