#!/usr/bin/env python3
# Stands in for the orca CLI: records calls, and plays each worker's step through the real harness hooks.
import json, os, re, subprocess, sys
state_path = os.environ["FAKE_ORCA_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"n": 0, "queue": [], "held": {}, "calls": [], "judged": 0}
args = [a for a in sys.argv[1:] if a != "--json"]
state["calls"].append(args[:2])
opt = lambda k: args[args.index(k) + 1] if k in args else None
def harness(cwd, *a, stdin=""):
    return subprocess.run(["python3", os.path.join(cwd, "scripts/harness/lib/harness.py")] + list(a), cwd=cwd, input=stdin, capture_output=True, text=True)
def done(d, h, body="ok", outcome="succeeded"):
    state["queue"].append({"id": "m%d" % len(state["calls"]), "type": "worker_done", "from_handle": h, "body": body, "payload": json.dumps({"dispatchId": d, "outcome": outcome})})
def report(agent, body):
    return json.dumps({"agent_type": agent, "last_assistant_message": "```json\n" + json.dumps(body) + "\n```"})
result = {}
if args[:2] == ["orchestration", "run-create"]:
    result = {"run": {"id": "run_test"}}
elif args[:2] == ["orchestration", "worker-start"]:
    state["n"] += 1
    d, h = "dispatch_%d" % state["n"], "term_%d" % state["n"]
    sel = opt("--worktree")
    cwd = next(w["path"] for w in state["worktrees"] if "id:" + w["id"] == sel) if sel.startswith("id:") else sel[len("path:"):]
    spec = opt("--spec")
    state.setdefault("specs", []).append(spec)
    state.setdefault("agents", []).append(opt("--agent") or opt("--terminal"))
    m = re.match(r"Harness step for task (\S+) \(\"[^\"]*\"\): (\w+)\.", spec)
    if spec.startswith("Harness question"):
        done(d, h, "ANSWER: recorded as A1 in the spec")
    elif m:
        task, step = m.groups()
        if step == "implement":
            os.makedirs(os.path.join(cwd, "src"), exist_ok=True); os.makedirs(os.path.join(cwd, "tests"), exist_ok=True)
            open(os.path.join(cwd, "src/feature_%s.py" % task.replace(".", "_")), "w").write("def f():  # AC-%s-1 AC-%s-2\n    return 1\n" % (task, task))
            open(os.path.join(cwd, "tests/test_feature_%s.py" % task.replace(".", "_")), "w").write("def test_f():  # AC-%s-1 AC-%s-2\n    assert True\n" % (task, task))
            state["queue"].append({"id": "q1", "type": "question", "from_handle": h, "body": "Which module holds f?", "payload": "{}"})
            state["held"][h] = d
        elif step == "judge":
            state["judged"] += 1
            verdict = "fail" if state["judged"] == 1 else "pass"
            crit = [{"id": "AC-%s-%d" % (task, n), "met": verdict == "pass", "evidence": "src/feature.py:1", "tests": ["test_f"]} for n in (1, 2)]
            harness(cwd, "hook", "judge-stop", stdin=report("judge", {"verdict": verdict, "task": task, "criteria": crit, "findings": [], "tests": {"command": "true", "result": "passed"}, "summary": "s"}))
            done(d, h)
        elif step == "diagnose":
            harness(cwd, "hook", "debug-stop", stdin=report("debugger", {"task": task, "root_causes": [{"criterion": "AC-%s-1" % task, "cause": "c", "fix": "f", "owner": "implementer"}], "confidence": "high", "summary": "s"}))
            done(d, h)
        elif step == "fix":
            if "fix" not in os.environ.get("FAKE_ORCA_IDLE", ""):
                open(os.path.join(cwd, "src/feature_%s.py" % task.replace(".", "_")), "a").write("# fixed\n")
            done(d, h)
        else:
            done(d, h)
    result = {"dispatch": {"dispatchId": d, "terminalHandle": h}}
elif args[:2] == ["repo", "add"]:
    result = {"repo": {"id": "repo1", "path": opt("--path")}}
elif args[:2] == ["worktree", "list"]:
    result = {"worktrees": state.get("worktrees", [])}
elif args[:2] == ["worktree", "create"]:
    name, repo = opt("--name"), opt("--repo")[len("path:"):]
    path = os.path.join(os.environ["FAKE_ORCA_WT"], name)
    subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", name, path, opt("--base-branch")], check=True)
    wt = {"id": "repo1::" + path, "path": path, "branch": "refs/heads/" + name, "displayName": name}
    state.setdefault("worktrees", []).append(wt)
    result = {"worktree": wt}
elif args[:2] == ["terminal", "create"]:
    state.setdefault("terminals", []).append(opt("--command"))
    result = {"terminal": {"handle": "term_launched_%d" % len(state["terminals"])}}
elif args[:2] == ["orchestration", "check"]:
    messages, state["queue"] = state["queue"], []
    result = {"deliveryId": "delivery_%d" % len(state["calls"]), "messages": messages}
elif args[:2] == ["orchestration", "reply"]:
    state.setdefault("replies", []).append([opt("--id"), opt("--body")])
    for h, d in list(state["held"].items()):
        done(d, h)
        del state["held"][h]
elif args[:2] == ["orchestration", "worker-show"]:
    result = {"dispatch": {"id": opt("--dispatch"), "status": "running"}}
elif args[:2] == ["orchestration", "worker-release"]:
    state.setdefault("released", []).append(opt("--dispatch"))
json.dump(state, open(state_path, "w"))
print(json.dumps({"ok": True, "result": result}))
