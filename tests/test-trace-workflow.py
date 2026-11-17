"""harness-verify's traceability steps (ADR-004, follow-ups 1, 2 and 4), run as CI runs them in throwaway projects.

The pull request job writes the HTML matrix with the base branch's engine and uploads it; the deliverer finds it and
links it from the pull request, and the user posts the link on the Linear ticket; the push job writes a .reqifz with the
engine the push starts from and signs it with the attest key. Nothing here reaches GitHub or Linear: the steps run
locally, the deliverer's commands go through its gate only, and the signature is made with a key made for the test.
The signing check needs cosign (brew install cosign) and is skipped without it.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from attest_support import FakeTokenService, left_in

HARNESS = Path(__file__).resolve().parents[1]
WORKFLOW = HARNESS / "payload/owned/.github/workflows/harness-verify.yml"
TAKE_BASE = "Take the verifier from the base branch"
TAKE_PUSHED = "Take the verifier from the commit before the push"
WRITE_MATRIX = "Write the traceability matrix"
UPLOAD_MATRIX = "Upload the traceability matrix"
WRITE_EXPORT = "Write the traceability export"
SIGN_EXPORT = "Sign the traceability export"
UPLOAD_EXPORT = "Upload the signed traceability export"
MATRIX = "harness-traceability/traceability.html"
EXPORT = "harness-traceability-signed/traceability.reqifz"
BUNDLE = "harness-traceability-signed/traceability.reqifz.sigstore.json"
SPEC = """# Spec 1.1: Customer search

Task: 1.1
PRD: none
Change-Class: feature

## Context
Support needs to find customers by name.

## Requirements
- REQ-1.1-1: The system shall return customers whose name contains the query, ignoring case.

## Acceptance criteria
- AC-1.1-1 (REQ-1.1-1): Given customers "Ana" and "Bob", when searching "an", then only "Ana" is returned.

## Non-functional requirements
- none

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
LINK = "https://github.com/o/r/actions/runs/123/artifacts/456"
# The deliverer's matrix step (.claude/agents/deliverer.md): find the harness-verify run of the pushed commit and its
# matrix, build the link's text, and add it to the pull request's body.
MATRIX_LINK_FLOW = (
    "gh run list --workflow harness-verify.yml --commit 3f2c1a9 --json databaseId --limit 1",
    "gh api repos/{owner}/{repo}/actions/runs/123/artifacts --jq "
    "'.artifacts[] | select(.name == \"harness-traceability\") | .id'",
    "python3 scripts/harness/lib/harness.py trace link %s" % LINK,
    "gh pr edit --body \"$(cat <<'EOF'\nWhat the branch does.\n\n**Traceability matrix** (ADR-004): %s\nEOF\n)\"" % LINK,
    "python3 scripts/harness/lib/harness.py linear receipt 1.1 --matrix %s --dry-run" % LINK)
# A stand-in for GitHub for the gate's own read of a pull request's labels; any other call fails.
FAKE_GH = """#!/bin/sh
case "$*" in
  "pr view"*"--json labels"*) echo '{"labels": []}' ;;
  *) echo "fake gh: no answer for: gh $*" >&2; exit 1 ;;
esac
"""


def environment(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="test",
               GIT_AUTHOR_EMAIL="test@example.com", GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.com",
               PYTHONDONTWRITEBYTECODE="1", HARNESS_VERIFY="off", HARNESS_TEST_CMD="true", HARNESS_REVIEW="off",
               HARNESS_DELIVER="off")
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


def step_text(name):
    """The harness-verify step called name, as the workflow writes it."""
    return re.split(r"\n(?=      - |  \S)", WORKFLOW.read_text().split("      - name: %s\n" % name, 1)[1], maxsplit=1)[0]


def step_script(name):
    return textwrap.dedent(step_text(name).split("        run: |\n", 1)[1])


def jobs():
    parts = re.split(r"\n(?=  [a-z-]+:\n)", WORKFLOW.read_text().split("\njobs:\n", 1)[1])
    return {part.split(":", 1)[0].strip(): part for part in parts}


def step_names(job):
    return [step.splitlines()[0] for step in jobs()[job].split("\n      - name: ")[1:]]


class Steps(unittest.TestCase):
    """A project that adopted this checkout's harness (self.adopted), then finished task 1.1 (self.tip). Each test works
    in its own clone."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="trace workflow ")
        cls.work = Path(cls.temp.name).resolve()
        cls.project = cls.work / "project"
        cls.project.mkdir()
        run(cls.project, "git", "init", "-q", "-b", "main")
        run(cls.project, HARNESS / "bootstrap.sh", cls.project, "--name", "workflow")
        cls.adopted = cls.commit(cls.project, "chore: adopt agentic harness")
        for name, text in (("src/search.py", "def search(names, q):\n    return [n for n in names if q in n]\n"),
                           ("tests/test_search.py", "def test_ac():  # AC-1.1-1\n    assert True\n"),
                           ("backbone/specs/1.1.md", SPEC)):
            (cls.project / name).parent.mkdir(parents=True, exist_ok=True)
            (cls.project / name).write_text(text)
        tasks = cls.project / "backbone/3-TASKS.md"
        tasks.write_text(tasks.read_text() + "\n- [WIP] **Task 1.1: Customer search** (spec: backbone/specs/1.1.md)\n")
        cls.hook("grill-stop", "griller", {"verdict": "pass", "task": "1.1", "questions": [], "summary": "s"})
        spec = cls.project / "backbone/specs/1.1.md"
        spec.write_text(spec.read_text() + "Approved-by: Ana (2026-11-01)\n")
        cls.hook("judge-stop", "judge", {
            "verdict": "pass", "task": "1.1", "summary": "s", "findings": [],
            "criteria": [{"id": "AC-1.1-1", "met": True, "evidence": "src/search.py:2", "tests": ["test_ac"]}],
            "tests": {"command": "true", "result": "passed"}})
        tasks.write_text(tasks.read_text().replace("- [WIP] **Task 1.1:", "- [x] **Task 1.1:"))
        cls.tip = cls.commit(cls.project, "feat: customer search")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def commit(cls, root, message):
        run(root, "git", "add", "-A")
        run(root, "git", "commit", "-qm", message)
        return run(root, "git", "rev-parse", "HEAD").stdout.strip()

    @classmethod
    def hook(cls, event, agent, report):
        stop = {"hook_event_name": "SubagentStop", "agent_type": agent, "stop_hook_active": False,
                "last_assistant_message": "Done.\n\n```json\n%s\n```" % json.dumps(report)}
        out = run(cls.project, "python3", "-B", cls.project / "scripts/harness/lib/harness.py", "hook", event,
                  input=json.dumps(stop), check=False, CLAUDE_PROJECT_DIR=str(cls.project))
        assert "PASS" in out.stdout + out.stderr, out.stdout + out.stderr

    def clone(self, name):
        root = self.work / name
        run(self.work, "git", "clone", "-q", "file://%s" % self.project, root)
        return root

    def runner(self, root):
        return Path(tempfile.mkdtemp(prefix="runner ", dir=str(root.parent)))

    def take_engine(self, root, ref, take=TAKE_BASE):
        """The take step as its job runs it: (runner's temp dir, the engine it leaves for the steps after it)."""
        runner = self.runner(root)
        ci = dict(BASE_REF=ref, RUNNER_TEMP=str(runner), GITHUB_ENV=str(runner / "github-env"))
        if take == TAKE_PUSHED:
            ci["REFUSE_FIRST_INSTALL"] = "true"
        run(root, "bash", "-e", "-o", "pipefail", "-c", step_script(take), **ci)
        return runner, (runner / "github-env").read_text().strip().split("=", 1)[1]

    def step(self, root, name, runner, **settings):
        return run(root, "bash", "-e", "-c", step_script(name), check=False, RUNNER_TEMP=str(runner),
                   HARNESS_ROOT=str(root), **settings)


class PullRequestMatrix(Steps):
    def test_the_matrix_of_a_pull_request_is_written_by_the_base_branch_engine(self):
        root = self.clone("changed-exporter")
        exporter = root / "scripts/harness/lib/traceability.py"
        exporter.write_text(exporter.read_text() + '\nFORMATS["html"] = (lambda model: "<p>every requirement is '
                                                   'proven</p>\\n", "traceability.html")\n')
        head = self.commit(root, "chore: describe the work kindly")
        own = run(root, "python3", "-B", root / "scripts/harness/lib/harness.py", "trace", "export", "--format", "html")
        run(root, "git", "update-ref", "refs/remotes/origin/review-base", self.adopted)
        runner, engine = self.take_engine(root, "origin/review-base")

        written = self.step(root, WRITE_MATRIX, runner, ENGINE_SCRIPT=engine)

        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        matrix = (runner / MATRIX).read_text()
        self.assertIn("every requirement is proven", own.stdout)
        self.assertNotIn("every requirement is proven", matrix)
        self.assertIn('<section id="task-1.1">', matrix)
        self.assertIn("HEAD %s" % head, matrix)

    def test_a_base_engine_without_the_export_writes_nothing_and_the_job_goes_on(self):
        root = self.clone("old-engine")
        run(root, "git", "checkout", "-q", "-b", "old", self.adopted)
        engine = root / "scripts/harness/lib/harness.py"
        engine.write_text(engine.read_text().replace('    if argv[:1] == ["export"]:\n', "    if False:\n", 1))
        self.commit(root, "chore: an engine from before trace export")
        run(root, "git", "checkout", "-q", "main")

        for take, write, folder in ((TAKE_BASE, WRITE_MATRIX, "harness-traceability"),
                                    (TAKE_PUSHED, WRITE_EXPORT, "harness-traceability-signed")):
            with self.subTest(step=write):
                runner, old = self.take_engine(root, "old", take=take)

                written = self.step(root, write, runner, ENGINE_SCRIPT=old)

                self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
                self.assertIn("::warning::", written.stdout)
                self.assertFalse((runner / folder).exists())

    def test_the_pull_request_job_writes_the_matrix_after_verifying_and_uploads_only_the_matrix(self):
        verify = jobs()["verify"]
        write, upload = step_text(WRITE_MATRIX), step_text(UPLOAD_MATRIX)

        self.assertEqual(step_names("verify"), [TAKE_BASE, "Verify the pull request's commits", WRITE_MATRIX,
                                                UPLOAD_MATRIX])
        self.assertIn('python3 "$ENGINE_SCRIPT" trace export --format html --out "$out"', write)
        self.assertIn("HARNESS_ROOT: ${{ github.workspace }}\n", write)
        self.assertEqual(verify.count("uses: actions/upload-artifact@"), 1)
        self.assertIn("uses: actions/upload-artifact@v7\n", upload)
        self.assertIn("name: harness-traceability\n", upload)
        self.assertIn("path: ${{ runner.temp }}/harness-traceability/\n", upload)
        self.assertIn("if-no-files-found: ignore\n", upload)


class SignedExport(Steps):
    def test_the_push_job_signs_a_reqifz_that_anyone_can_check_and_regenerate(self):
        cosign = shutil.which("cosign")
        if cosign is None:
            self.skipTest("cosign is not installed (brew install cosign); the signing step needs it")
        root = self.clone("signed")
        keys = self.work / "keys"
        keys.mkdir()
        run(keys, cosign, "generate-key-pair", COSIGN_PASSWORD="pw")
        runner, engine = self.take_engine(root, self.adopted, take=TAKE_PUSHED)
        (runner / "cosign").symlink_to(cosign)

        written = self.step(root, WRITE_EXPORT, runner, ENGINE_SCRIPT=engine)
        signed = self.step(root, SIGN_EXPORT, runner, ATTEST_MODE="key",
                           HARNESS_ATTEST_KEY=(keys / "cosign.key").read_text(), COSIGN_PASSWORD="pw")

        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        check = (cosign, "verify-blob", "--key", keys / "cosign.pub", "--bundle", runner / BUNDLE,
                 "--insecure-ignore-tlog")
        self.assertEqual(run(self.work, *check, runner / EXPORT, check=False).returncode, 0)
        again = self.clone("regenerated")
        out = self.work / "regenerated-export"
        run(again, "python3", "-B", again / "scripts/harness/lib/harness.py", "trace", "export", "--format", "reqifz",
            "--out", out)
        self.assertEqual((out / "traceability.reqifz").read_bytes(), (runner / EXPORT).read_bytes())
        tampered = self.work / "tampered.reqifz"
        tampered.write_bytes((runner / EXPORT).read_bytes() + b"\0")
        self.assertNotEqual(run(self.work, *check, tampered, check=False).returncode, 0)

    def test_without_an_export_the_signing_step_signs_nothing(self):
        runner = self.runner(self.project)

        signed = self.step(self.project, SIGN_EXPORT, runner, ATTEST_MODE="key", HARNESS_ATTEST_KEY="unused",
                           COSIGN_PASSWORD="pw")

        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        self.assertEqual(list(runner.iterdir()), [])

    def signable_export(self, name):
        cosign = shutil.which("cosign")
        if cosign is None:
            self.skipTest("cosign is not installed (brew install cosign); the signing step needs it")
        root = self.clone(name)
        runner, engine = self.take_engine(root, self.adopted, take=TAKE_PUSHED)
        (runner / "cosign").symlink_to(cosign)
        written = self.step(root, WRITE_EXPORT, runner, ENGINE_SCRIPT=engine)
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        return cosign, root, runner

    def test_the_kms_mode_signs_the_export_with_the_reference_and_a_fresh_token_it_leaves_to_no_later_step(self):
        cosign, root, runner = self.signable_export("signed-kms")
        keys = self.work / "kms-keys"
        keys.mkdir()
        run(keys, cosign, "generate-key-pair", COSIGN_PASSWORD="")
        service = FakeTokenService(self, vault_token="a-vault-token")
        address = service.settings["ACTIONS_ID_TOKEN_REQUEST_URL"].split("/token", 1)[0]
        before = (runner / "github-env").read_text()

        signed = self.step(root, SIGN_EXPORT, runner, ATTEST_MODE="kms", ATTEST_KMS_KEY=str(keys / "cosign.key"),
                           ATTEST_KMS_CLOUD="vault", ATTEST_VAULT_ADDR=address, ATTEST_VAULT_ROLE="harness-attest",
                           ATTEST_OIDC_AUDIENCE=address, COSIGN_PASSWORD="", GITHUB_ENV=str(runner / "github-env"),
                           **service.settings)

        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        self.assertEqual(service.audiences, [address])
        self.assertEqual(service.logins, [{"role": "harness-attest", "jwt": "a.github.oidc.token"}])
        self.assertEqual((runner / "github-env").read_text(), before)
        self.assertEqual(left_in(runner, "a.github.oidc.token", "a-vault-token"), [])
        check = run(self.work, cosign, "verify-blob", "--key", keys / "cosign.pub", "--bundle", runner / BUNDLE,
                    "--insecure-ignore-tlog", runner / EXPORT, check=False)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_the_export_signing_never_falls_back_to_keyless(self):
        _, root, runner = self.signable_export("no-fallback")
        cases = {"kms without a reference": dict(ATTEST_MODE="kms", ATTEST_KMS_KEY=""),
                 "key without the secret": dict(ATTEST_MODE="key", HARNESS_ATTEST_KEY=""),
                 "no mode": dict(ATTEST_MODE=""), "an unknown mode": dict(ATTEST_MODE="sigstore")}
        for case, ci in cases.items():
            with self.subTest(case=case):
                signed = self.step(root, SIGN_EXPORT, runner, COSIGN_PASSWORD="", **ci)

                self.assertNotEqual(signed.returncode, 0, signed.stdout)
                self.assertFalse((runner / BUNDLE).exists())

    def test_the_export_is_signed_by_the_verdict_attestation_s_signer(self):
        branches = dict(re.findall(r"^  (\w+)\)\n((?:    .*\n)+?)    ;;", step_script(SIGN_EXPORT), re.M))

        self.assertEqual(sorted(branches), ["key", "keyless", "kms"])
        self.assertIn("--key env://HARNESS_ATTEST_KEY", branches["key"])
        self.assertIn('--key "$ATTEST_KMS_KEY"', branches["kms"])
        for mode in ("key", "kms"):
            self.assertIn('--signing-config "$RUNNER_TEMP/signing-config.json"', branches[mode])
        self.assertNotIn("--key", branches["keyless"])
        self.assertNotIn("--signing-config", branches["keyless"])
        for name in (WRITE_EXPORT, SIGN_EXPORT, UPLOAD_EXPORT):
            self.assertIn("if: env.ATTEST == 'true'\n", step_text(name))
        self.assertNotIn("secrets.", step_text(WRITE_EXPORT))

    def test_the_push_job_signs_the_export_last_with_the_checked_key_and_keeps_it(self):
        sign, upload = step_text(SIGN_EXPORT), step_text(UPLOAD_EXPORT)

        self.assertEqual(step_names("attest")[-4:], ["Upload the verdict attestation", WRITE_EXPORT, SIGN_EXPORT,
                                                     UPLOAD_EXPORT])
        self.assertIn('python3 "$ENGINE_SCRIPT" trace export --format reqifz --out "$out"', step_text(WRITE_EXPORT))
        self.assertIn("HARNESS_ATTEST_KEY: ${{ secrets.HARNESS_ATTEST_KEY }}\n", sign)
        self.assertIn("--key env://HARNESS_ATTEST_KEY", sign)
        self.assertIn("name: harness-traceability-signed\n", upload)
        self.assertIn("path: ${{ runner.temp }}/harness-traceability-signed/\n", upload)


class DelivererLink(Steps):
    """The deliverer's gate on the commands that link the matrix, in a clone on a feature branch with a GitHub origin."""

    def decision(self, root, command, fake):
        hook_input = {"session_id": "s", "agent_id": "a1", "agent_type": "deliverer", "tool_name": "Bash",
                      "tool_input": {"command": command}}
        result = run(root, "python3", "-B", root / "scripts/harness/lib/harness.py", "hook", "pre-tool-use",
                     input=json.dumps(hook_input), check=False, CLAUDE_PROJECT_DIR=str(root),
                     PATH="%s%s%s" % (fake, os.pathsep, os.environ["PATH"]))
        return result.returncode, result.stderr

    def gated_clone(self, name):
        root = self.clone(name)
        run(root, "git", "remote", "set-url", "origin", "git@github.com:o/r.git")
        run(root, "git", "checkout", "-q", "-b", "feat/search")
        fake = self.work / ("%s-bin" % name)
        fake.mkdir()
        (fake / "gh").write_text(FAKE_GH)
        (fake / "gh").chmod(0o755)
        return root, fake

    def test_the_deliverer_may_find_the_matrix_and_link_it_from_the_pull_request(self):
        root, fake = self.gated_clone("deliverer")
        for command in MATRIX_LINK_FLOW:
            with self.subTest(command=command):
                code, message = self.decision(root, command, fake)

                self.assertEqual(code, 0, message)

    def test_posting_the_link_as_a_comment_or_on_linear_stays_the_users_call(self):
        root, fake = self.gated_clone("users-call")
        for command in ("gh pr comment 7 --body %s" % LINK,
                        "python3 scripts/harness/lib/harness.py linear receipt 1.1 --matrix %s" % LINK):
            with self.subTest(command=command):
                code, message = self.decision(root, command, fake)

                self.assertEqual(code, 2, message)

    def test_the_deliverer_s_instructions_name_the_matrix_step(self):
        instructions = (HARNESS / "payload/owned/.claude/agents/deliverer.md").read_text()

        for text in ("gh run list --workflow harness-verify.yml --commit <head> --json databaseId --limit 1",
                     "gh api repos/{owner}/{repo}/actions/runs/<run-id>/artifacts --jq "
                     "'.artifacts[] | select(.name == \"harness-traceability\") | .id'",
                     "python3 scripts/harness/lib/harness.py trace link "
                     "https://github.com/<owner>/<repo>/actions/runs/<run-id>/artifacts/<artifact-id>",
                     "linear receipt <id> --matrix <url>"):
            with self.subTest(text=text):
                self.assertIn(text, instructions)


if __name__ == "__main__":
    unittest.main()
