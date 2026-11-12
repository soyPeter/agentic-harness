"""Shared by the attest test files (ADR-005): throwaway projects with this checkout installed, the steps of
harness-verify as CI runs them, and stand-ins for the two services the checks can't reach (GitHub's API and its OIDC
token endpoint)."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from urllib.parse import parse_qs, urlparse


HARNESS = Path(__file__).resolve().parents[1]
ENGINE = HARNESS / "payload/owned/scripts/harness/lib/harness.py"
LAUNCHER = HARNESS / "plugin/launcher.py"
WORKFLOW = HARNESS / "payload/owned/.github/workflows/harness-verify.yml"
VERSION = (HARNESS / "VERSION").read_text().strip()
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_V01 = "https://github.com/soyPeter/agentic-harness/attestation/verdicts/v0.1"
PREDICATE_TYPE = "https://github.com/soyPeter/agentic-harness/attestation/verdicts/v1"
VERIFIER = "https://github.com/soyPeter/agentic-harness"
LENSES = ("correctness", "structure", "lean")
APPROVAL = "Approved-by: Ana (2026-11-01)"
STATEMENT_FILE = "harness-attestation/harness-verdicts.intoto.json"
BUNDLE_FILE = "harness-attestation/harness-verdicts.sigstore.json"
SPEC = """# Spec {task}: {title}

Task: {task}
PRD: none
Change-Class: {change_class}

## Context
Support needs to find customers by name.

## Requirements
- REQ-{task}-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-{task}-1 (REQ-{task}-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

## Non-functional requirements
- Search answers within 200 ms.

## Architecture
ADRs: ADR-001
Tech requirements:
- The code lives in src/.

## Skills
- code-quality: all code

## Out of scope
- Fuzzy matching.

## Assumptions
- none

## Open questions
- none

## Approval
"""
SEARCH = {"src/search.py": "def search(names, query):\n    return [n for n in names if query.lower() in n.lower()]\n",
          "tests/test_search.py": "def test_ac():  # AC-1.1-1\n    assert True\n"}
# Rewrites src/search.py at another size, so the judge's fingerprint can't read a stale index entry.
SORT = {"src/sort.py": "def by_name(names):\n    return sorted(names, key=str.lower)\n",
        "src/search.py": "def search(names, query):\n    query = query.lower()\n"
                         "    return [n for n in names if query in n.lower()]\n",
        "tests/test_sort.py": "def test_ac():  # AC-1.2-1\n    assert True\n"}


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="test",
               GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com",
               PYTHONDONTWRITEBYTECODE="1", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true")
    env.update(settings)
    return env


def run(cwd, *args, input=None, check=True, **settings):
    streams = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
    result = subprocess.run([str(a) for a in args], cwd=str(cwd), env=environment(**settings), capture_output=True,
                            text=True, **streams)
    if check and result.returncode:
        raise AssertionError("%s failed (exit %d):\n%s%s" % (" ".join(map(str, args)), result.returncode,
                                                             result.stdout, result.stderr))
    return result


def sha256(data):
    return hashlib.sha256(data).hexdigest()


TAKE_BASE = "Take the verifier from the base branch"
CHOOSE_JOB = "Choose the attest job"
TAKE_PUSHED = "Take the verifier from the commit before the push"
FIND_SETTINGS = "Find the signing settings"
CHECK_PUSHED = "Check the pushed range"
CHECK_SIGNING = "Check the signing settings"
CHECK_ENVIRONMENT = "Check the harness-attest environment"
INSTALL_COSIGN = "Install cosign"
CHECK_KEY = "Check the attestation key"
READ_APPROVAL = "Read the merged pull request's approval"
WRITE = "Write the verdict attestation"
SIGN = "Sign the verdict attestation"
UPLOAD = "Upload the verdict attestation"
WRITE_EXPORT = "Write the traceability export"
SIGN_EXPORT = "Sign the traceability export"
UPLOAD_EXPORT = "Upload the signed traceability export"


def step_script(name, source=None):
    """The shell script of the harness-verify step called name, with the harness repository's URL pointed at
    source."""
    step = WORKFLOW.read_text().split("      - name: %s\n" % name, 1)[1]
    script = textwrap.dedent(re.split(r"\n(?=      - name:|  \S)", step.split("        run: |\n", 1)[1], maxsplit=1)[0])
    return script.replace("https://github.com/soyPeter/agentic-harness.git", str(source)) if source else script


def jobs():
    """The workflow's jobs, by name, as text."""
    parts = re.split(r"\n(?=  [a-z-]+:\n)", WORKFLOW.read_text().split("\njobs:\n", 1)[1])
    return {part.split(":", 1)[0].strip(): part for part in parts}


def step_text(job, name):
    """The whole of a step of job (its if, env and run), as text."""
    return jobs()[job].split("\n      - name: %s\n" % name, 1)[1].split("\n      - name:", 1)[0]


# A stand-in for GitHub, the one service these checks can't reach: it answers a read (gh api <endpoint>, gh repo view)
# with the JSON a test put under the exact command line in $FAKE_GH_ANSWERS, accepts every write, and logs every call
# to $FAKE_GH_LOG. With $FAKE_GH_TOKEN set, it answers only a call made with GH_TOKEN equal to it.
FAKE_GH = """#!%s
import json, os, sys
words = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(words) + "\\n")
answers = json.load(open(os.environ["FAKE_GH_ANSWERS"]))
if os.environ.get("FAKE_GH_TOKEN") and os.environ.get("GH_TOKEN") != os.environ["FAKE_GH_TOKEN"]:
    sys.exit("fake gh: no token")
if " ".join(words) in answers:
    print(json.dumps(answers[" ".join(words)]))
elif words[:2] == ["api", "-X"] or words[:1] in (["variable"], ["secret"]):
    pass
else:
    sys.exit("fake gh: no answer for: gh " + " ".join(words))
"""


def fake_github(folder, answers):
    """A bin folder holding the fake gh, and the settings that point it at answers."""
    (folder / "bin").mkdir(parents=True, exist_ok=True)
    (folder / "bin" / "gh").write_text(FAKE_GH % sys.executable)
    (folder / "bin" / "gh").chmod(0o755)
    (folder / "answers.json").write_text(json.dumps(answers))
    return folder / "bin", dict(FAKE_GH_ANSWERS=str(folder / "answers.json"), FAKE_GH_LOG=str(folder / "gh.log"))


def gh_calls(folder):
    log = folder / "gh.log"
    return log.read_text().splitlines() if log.exists() else []


class FakeTokenService:
    """A stand-in for GitHub's OIDC token endpoint (ACTIONS_ID_TOKEN_REQUEST_URL), the other service a job reaches:
    it answers a request carrying the runner's request token with the job's token, and records the audience asked
    for. answer, when given, is the body of every answer instead. With vault_token, it also stands in for a Vault
    server's JWT login (POST /v1/auth/jwt/login), recording each login and answering with vault_token."""

    def __init__(self, test, token="a.github.oidc.token", answer=None, vault_token=None,
                 request_token="runner-request-token"):
        self.audiences, self.logins = [], []
        service = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, status, body=b""):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get("Authorization") != "bearer " + request_token:
                    return self.reply(401)
                service.audiences += parse_qs(urlparse(self.path).query).get("audience", [""])
                self.reply(200, (answer if answer is not None else json.dumps({"count": 1, "value": token})).encode())

            def do_POST(self):
                if vault_token is None or urlparse(self.path).path != "/v1/auth/jwt/login":
                    return self.reply(404)
                service.logins.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0))))
                self.reply(200, json.dumps({"auth": {"client_token": vault_token}}).encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.server.server_close)
        test.addCleanup(self.server.shutdown)
        self.settings = dict(ACTIONS_ID_TOKEN_REQUEST_URL="http://127.0.0.1:%d/token?api-version=2.0"
                             % self.server.server_address[1], ACTIONS_ID_TOKEN_REQUEST_TOKEN=request_token)


class Project:
    """A throwaway repository holding an install of this checkout as its first commit, self.adopted. settings go
    into the environment of every command run in it."""

    def __init__(self, root, installer=None, **settings):
        self.root = root
        self.settings = settings
        root.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        if installer:
            installer(self)
        else:
            self.run(HARNESS / "bootstrap.sh", root, "--name", "attest")
        self.adopted = self.commit("chore: adopt the agentic harness")

    @property
    def engine(self):
        return self.root / "scripts/harness/lib/harness.py"

    def run(self, *args, **options):
        return run(self.root, *args, **dict(self.settings, **options))

    def git(self, *args):
        return self.run("git", *args).stdout.strip()

    def harness(self, *args, check=False, **settings):
        return self.run("python3", "-B", self.engine, *args, check=check, **settings)

    def attest(self, base, *flags, **settings):
        return self.harness("attest", "--range", "%s..HEAD" % base, *flags, **settings)

    def statement(self, base, *flags, **settings):
        return json.loads(self.attest(base, *flags, check=True, **settings).stdout)

    def hook(self, event, agent, report):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(report)}
        self.run("python3", "-B", self.engine, "hook", event, CLAUDE_PROJECT_DIR=str(self.root), input=json.dumps(stop))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append(self, name, text):
        with open(str(self.root / name), "a", encoding="utf-8") as handle:
            handle.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD")

    def set_marker(self, task, old, new):
        # The seed's comment shows an example "- [ ] **Task 1.1:" line above the real ones.
        head, line, tail = (self.root / "backbone/3-TASKS.md").read_text(encoding="utf-8").rpartition(
            "- [%s] **Task %s:" % (old, task))
        self.write("backbone/3-TASKS.md", head + line.replace("[%s]" % old, "[%s]" % new, 1) + tail)

    def specify(self, task, title, change_class="feature"):
        """task's spec, grilled and approved by the user, committed with its pending task line."""
        self.write("backbone/specs/%s.md" % task, SPEC.format(task=task, title=title, change_class=change_class))
        self.append("backbone/3-TASKS.md", "- [ ] **Task %s: %s** (spec: backbone/specs/%s.md)\n" % (task, title, task))
        self.hook("grill-stop", "griller", {"verdict": "pass", "task": task, "questions": [], "summary": "s"})
        self.append("backbone/specs/%s.md" % task, APPROVAL + "\n")
        return self.commit("docs: spec for task %s" % task)

    def build(self, task, files):
        """task's change (files), judged and reviewed through every lens on that code, marked done and committed."""
        self.set_marker(task, " ", "WIP")
        for name, text in files.items():
            self.write(name, text)
        self.hook("judge-stop", "judge", {
            "verdict": "pass", "task": task, "summary": "s", "findings": [],
            "criteria": [{"id": "AC-%s-1" % task, "met": True, "evidence": "src", "tests": ["test_ac"]}],
            "tests": {"command": "true", "result": "passed"}})
        for lens in LENSES:
            self.hook("review-stop", "reviewer", {"task": task, "lens": lens, "verdict": "pass", "findings": [],
                                                  "summary": "s"})
        self.set_marker(task, "WIP", "x")
        return self.commit("feat: task %s" % task)

    def finish(self, task, title, files, change_class="feature"):
        self.specify(task, title, change_class)
        return self.build(task, files)

    def verdicts(self, task, kind):
        return json.loads((self.root / ("backbone/.verdicts/%s.%s.json" % (task, kind))).read_text())["history"]


def new_project(test, **settings):
    temp = tempfile.TemporaryDirectory(prefix="attest ")
    test.addCleanup(temp.cleanup)
    return Project(Path(temp.name).resolve() / "project", **settings)


def runner_folder(project):
    """A fresh $RUNNER_TEMP next to project."""
    return Path(tempfile.mkdtemp(prefix="runner ", dir=str(project.root.parent)))


def run_take(project, ref, step=TAKE_PUSHED, source=None):
    """The take step as its job runs it: (the step's result, runner's temp dir). The attest job's take step runs
    with REFUSE_FIRST_INSTALL on, as the workflow sets it."""
    runner = runner_folder(project)
    ci = dict(BASE_REF=ref, RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"))
    if step == TAKE_PUSHED:
        ci["REFUSE_FIRST_INSTALL"] = "true"
    result = project.run("bash", "-e", "-o", "pipefail", "-c", step_script(step, source), check=False, **ci)
    return result, runner


def take_engine(project, ref, step=TAKE_PUSHED, source=None):
    """(runner's temp dir, the engine the take step leaves for the steps after it)."""
    result, runner = run_take(project, ref, step, source)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return runner, (runner / "github-env").read_text().strip().split("=", 1)[1]


# Runs the real cosign, after recording what its KMS client would read: the cloud's variables in its environment and the
# files they name. The clouds themselves can't be reached, so this is how a check sees the login a signing step made.
RECORDING_COSIGN = """#!%s
import json, os, sys
names = ("GOOGLE_APPLICATION_CREDENTIALS", "AWS_ROLE_ARN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_REGION",
         "AWS_ROLE_SESSION_NAME", "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_FEDERATED_TOKEN_FILE", "VAULT_ADDR",
         "VAULT_TOKEN")
seen = {name: os.environ[name] for name in names if name in os.environ}
files = {}
for name in ("GOOGLE_APPLICATION_CREDENTIALS", "AWS_WEB_IDENTITY_TOKEN_FILE", "AZURE_FEDERATED_TOKEN_FILE"):
    if os.path.isfile(seen.get(name, "")):
        files[name] = open(seen[name]).read()
with open(os.environ["COSIGN_RECORD"], "a") as record:
    record.write(json.dumps({"args": sys.argv[1:], "variables": seen, "files": files}) + "\\n")
os.execv(%r, [%r] + sys.argv[1:])
"""


def recording_cosign(runner, cosign):
    """runner's cosign, recording each call to the list recording_cosign_calls(runner) returns."""
    (runner / "cosign").write_text(RECORDING_COSIGN % (sys.executable, cosign, cosign))
    (runner / "cosign").chmod(0o755)
    return dict(COSIGN_RECORD=str(runner.parent / (runner.name + ".cosign-calls")))


def recording_cosign_calls(runner):
    record = runner.parent / (runner.name + ".cosign-calls")
    return [json.loads(line) for line in record.read_text().splitlines()] if record.exists() else []


def left_in(runner, *secrets):
    """The files under runner holding any of secrets."""
    return sorted(str(path.relative_to(runner)) for path in runner.rglob("*")
                  if path.is_file() and not path.is_symlink() and any(s in path.read_text(errors="replace")
                                                                          for s in secrets))


def github_env(runner):
    """The variables the steps so far wrote to $GITHUB_ENV, as the runner reads them."""
    path = runner / "github-env"
    return dict(line.split("=", 1) for line in path.read_text().splitlines()) if path.exists() else {}


def run_step(project, name, runner, **ci):
    """A step of the attest job, run as the runner runs it (bash -e -o pipefail), with the variables earlier steps
    wrote to $GITHUB_ENV and ci."""
    settings = dict(github_env(runner), RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"), **ci)
    return project.run("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step_script(name), check=False,
                       **settings)


def cosign_or_skip(test):
    """The cosign binary, or skip test: signing and checking a signature are cosign's job."""
    cosign = shutil.which("cosign")
    if cosign is None:
        test.skipTest("cosign is not installed (brew install cosign); this check runs it")
    return cosign


def key_pair(test, folder, cosign, password="pw"):
    """A cosign key pair in folder: (private key text, public key text)."""
    folder.mkdir(parents=True, exist_ok=True)
    run(folder, cosign, "generate-key-pair", COSIGN_PASSWORD=password)
    return (folder / "cosign.key").read_text(), (folder / "cosign.pub").read_text()
