"""harness-verify's attest job beyond the plain key (ADR-005 follow-ups 1 to 3): the merged pull request's approval
label, and the signing modes (the key in the environment, a cloud KMS key, keyless), run as CI runs them in throwaway
projects.

GitHub's API and its OIDC token endpoint are the services these checks can't reach; stand-ins answer for them (the
fake gh, FakeTokenService). No cloud, Vault or Sigstore service is reached: what a KMS login or a keyless signature does
past the job's own files and variables is not tested here. The checks that run cosign skip without it. The property
checks need hypothesis (pip install -r tests/requirements.txt) and are skipped without it.
"""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest

from attest_support import (BUNDLE_FILE, CHECK_KEY, CHECK_SIGNING, CHOOSE_JOB, FIND_SETTINGS, READ_APPROVAL, SEARCH,
                            SIGN, SIGN_EXPORT, STATEMENT_FILE, WORKFLOW, WRITE, FakeTokenService, Project,
                            cosign_or_skip, fake_github, github_env, jobs, key_pair, left_in, new_project,
                            recording_cosign, recording_cosign_calls, run, run_step, runner_folder, sha256, step_script,
                            step_text, take_engine)
from hypothesis_profiles import examples

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError:
    given = None


LABEL = "harness-change-approved"
GCP_KEY = "gcpkms://projects/p/locations/europe-west1/keyRings/harness/cryptoKeys/attest/cryptoKeyVersions/1"
GCP_PROVIDER = "projects/123456/locations/global/workloadIdentityPools/github/providers/harness"
GCP_ACCOUNT = "attest@p.iam.gserviceaccount.com"
AWS_KEY = "awskms:///arn:aws:kms:eu-west-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab"
AWS_ROLE = "arn:aws:iam::111122223333:role/harness-attest"
AZURE_KEY = "azurekms://harness.vault.azure.net/attest"
AZURE_TENANT = "00000000-1111-2222-3333-444444444444"
AZURE_CLIENT = "55555555-6666-7777-8888-999999999999"
VAULT_KEY = "hashivault://harness-attest"


def pull(number=7, merge=None, head=None, base="main", merged=True, labels=(LABEL,)):
    """A pull request as GET repos/<r>/commits/<sha>/pulls lists it (the fields the check reads)."""
    return {"number": number, "state": "closed" if merged else "open", "merged_at": "2026-11-11T10:00:00Z" if merged
            else None, "merge_commit_sha": merge, "head": {"sha": head, "ref": "feature"}, "base": {"ref": base},
            "labels": [{"name": name} for name in labels]}


class ApprovalProject(unittest.TestCase):
    """A project whose main can move to a squash merge, a merge commit of a two-commit branch, a rebase of two
    commits, or a squash on an unrelated commit, each a harness change."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="approval ")
        cls.addClassCleanup(temp.cleanup)
        cls.folder = Path(temp.name).resolve()
        project = cls.project = Project(cls.folder / "project")
        base = cls.base = project.adopted
        project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n')
        cls.squash = project.commit("chore: switch the reviews off (#7)")
        project.git("checkout", "-q", "-b", "feature", base)
        project.append("notes.md", "one\n")
        project.commit("docs: one")
        project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n')
        cls.head = project.commit("chore: switch the reviews off")
        project.git("checkout", "-q", "-b", "merged", base)
        project.git("merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #7 from feature")
        cls.merge = project.git("rev-parse", "HEAD")
        project.git("checkout", "-q", "-b", "rebased", base)
        project.append("notes.md", "one\n")
        project.commit("docs: one")
        project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n')
        cls.rebased = project.commit("chore: switch the reviews off")
        project.git("checkout", "-q", "-b", "extra", base)
        project.append("notes.md", "unrelated\n")
        project.commit("docs: an unrelated commit")
        project.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n')
        cls.extra = project.commit("chore: switch the reviews off (#7)")
        cls.calls = 0

    def check(self, pulls, tip, base=None, branch="main"):
        type(self).calls += 1
        answer = self.folder / ("pulls-%d.json" % self.calls)
        answer.write_text(pulls if isinstance(pulls, str) else json.dumps(pulls))
        return self.project.harness("approval-check", answer, "%s..%s" % (base or self.base, tip), branch)

    def assert_approved(self, result, number=7):
        self.assertEqual((result.returncode, result.stdout), (0, "%d\n" % number), result.stderr)
        self.assertIn("pull request #%d" % number, result.stderr)

    def assert_refused(self, result, reason):
        self.assertEqual((result.returncode, result.stdout), (1, ""), result.stderr)
        self.assertIn(reason, result.stderr)


class ApprovalCheck(ApprovalProject):
    """harness.py approval-check: whether the pull request GitHub lists for a pushed commit approved the whole push.
    The push is that pull request's merge alone: one commit on the previous tip (a squash, or a rebase of one
    commit), or a merge commit of the previous tip and the pull request's head."""

    def test_a_labelled_squash_merge_approves_its_push(self):
        self.assert_approved(self.check([pull(merge=self.squash, head=self.head)], self.squash))

    def test_a_labelled_merge_commit_of_the_pull_requests_head_approves_its_push(self):
        self.assert_approved(self.check([pull(merge=self.merge, head=self.head)], self.merge))

    def test_a_merge_commit_of_another_head_is_more_than_the_pull_request(self):
        self.assert_refused(self.check([pull(merge=self.merge, head=self.squash)], self.merge),
                            "the push is more than pull request #7's merge")

    def test_a_push_of_several_commits_on_the_previous_tip_is_more_than_one_merge(self):
        self.assert_refused(self.check([pull(merge=self.rebased, head=self.head)], self.rebased),
                            "the push is more than pull request #7's merge")

    def test_a_push_that_holds_another_commit_before_the_merge_is_more_than_the_merge(self):
        self.assert_refused(self.check([pull(merge=self.extra, head=self.head)], self.extra),
                            "the push is more than pull request #7's merge")

    def test_an_unlabelled_pull_request_approves_nothing(self):
        self.assert_refused(self.check([pull(merge=self.squash, labels=("bug",))], self.squash),
                            "pull request #7 doesn't carry harness-change-approved")

    def test_only_a_pull_request_merged_into_the_pushed_branch_as_the_pushed_commit_counts(self):
        cases = {"open": pull(merge=self.squash, merged=False),
                 "merged into another branch": pull(merge=self.squash, base="develop"),
                 "merged as another commit": pull(merge=self.merge),
                 "no merge commit": pull(merge=None)}
        for case, record in cases.items():
            with self.subTest(case=case):
                self.assert_refused(self.check([record], self.squash),
                                    "no pull request merged into main has %s as its merge commit" % self.squash[:12])

    def test_two_pull_requests_naming_the_same_merge_commit_approve_nothing(self):
        self.assert_refused(self.check([pull(7, merge=self.squash), pull(8, merge=self.squash)], self.squash),
                            "pull requests #7 and #8 both name")

    def test_an_answer_that_is_not_a_list_of_pull_requests_approves_nothing(self):
        for answer in ("not json", '{"message": "Not Found"}', "null", "[1, 2]"):
            with self.subTest(answer=answer):
                self.assertEqual(self.check(answer, self.squash).returncode, 1)

    def test_a_range_that_is_not_two_commits_is_a_usage_error_or_refused(self):
        usage = self.project.harness("approval-check", "pulls.json", "HEAD")
        missing = self.check([pull(merge=self.squash)], "no-such-commit")

        self.assertEqual(usage.returncode, 64)
        self.assertIn("usage: harness.py approval-check <pulls.json> <base>..<tip> <branch>", usage.stderr)
        self.assert_refused(missing, "no-such-commit is not a commit")


if given is not None:
    OTHERS = st.lists(st.builds(
        pull, number=st.integers(8, 99), merge=st.sampled_from([None, "0" * 40]), head=st.just(None),
        base=st.sampled_from(["main", "develop"]), merged=st.booleans(),
        labels=st.lists(st.sampled_from([LABEL, "bug", "risk:high"]), max_size=2).map(tuple)), max_size=3)

    class ApprovalProperties(ApprovalProject):
        """Other pull requests GitHub lists for the commit (open ones, ones merged elsewhere or as other commits) and
        the order of the list never change the answer; the label on the merged one decides it."""

        @settings(max_examples=examples(20), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(others=OTHERS, labelled=st.booleans(), shuffle=st.randoms(use_true_random=False))
        def test_unrelated_pull_requests_and_their_order_change_nothing(self, others, labelled, shuffle):
            merged = pull(merge=self.squash, labels=(LABEL,) if labelled else ("bug",))
            listed = others + [merged]
            shuffle.shuffle(listed)

            result = self.check(listed, self.squash)

            self.assertEqual(result.stdout, "7\n" if labelled else "")
            self.assertEqual(result.returncode, 0 if labelled else 1, result.stderr)

        @settings(max_examples=examples(10), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(others=OTHERS)
        def test_a_label_on_any_other_pull_request_approves_nothing(self, others):
            labelled = [dict(record, labels=[{"name": LABEL}]) for record in others]

            result = self.check(labelled + [pull(merge=self.squash, labels=())], self.squash)

            self.assertEqual((result.returncode, result.stdout), (1, ""), result.stderr)


class ApprovalStep(unittest.TestCase):
    """The attest job's approval step, then its statement step, for a push made by merging a pull request: the
    engine is still the one the push starts from, and the approval is recorded in the statement."""

    def push(self, project, change):
        """The previous tip, and a pushed commit on it that makes change (a function of the project)."""
        before = project.git("rev-parse", "HEAD")
        change(project)
        return before, project.commit("chore: a harness change (#7)")

    def approval_step(self, project, runner, before, answer):
        """The approval step with a fake gh: answer is GitHub's list for the pushed commit, or None when the read
        fails."""
        tip = project.git("rev-parse", "HEAD")
        answers = {} if answer is None else {"api repos/owner/attest/commits/%s/pulls" % tip: answer}
        bin_folder, settings = fake_github(runner / "github", answers)
        return run_step(project, READ_APPROVAL, runner, PATH="%s:%s" % (bin_folder, os.environ["PATH"]),
                        GH_TOKEN="job-token",
                        FAKE_GH_TOKEN="job-token", REPOSITORY="owner/attest", BRANCH="main", BEFORE=before,
                        GITHUB_SHA=tip, **settings)

    def write(self, project, runner, before):
        return run_step(project, WRITE, runner, HARNESS_ROOT=str(project.root), BEFORE=before)

    def test_an_approved_harness_change_gets_a_statement_from_the_engine_the_push_starts_from(self):
        project = new_project(self)
        before, tip = self.push(project, lambda p: p.append("scripts/harness/lib/harness.py", "# approved\n"))
        runner, _ = take_engine(project, before)

        approval = self.approval_step(project, runner, before, [pull(merge=tip, head="f" * 40)])
        written = self.write(project, runner, before)

        self.assertEqual(approval.returncode, 0, approval.stdout + approval.stderr)
        self.assertEqual(github_env(runner).get("ATTEST_PULL_REQUEST"), "7")
        self.assertEqual(written.returncode, 0, written.stderr)
        made = json.loads((runner / STATEMENT_FILE).read_text())
        verification = made["predicate"]["verification"]
        self.assertEqual((verification["allowUserChanges"], verification["approval"]),
                         (True, {"label": LABEL, "pullRequest": 7}))
        engine_before = project.run("git", "show", "%s:scripts/harness/lib/harness.py" % before).stdout
        self.assertEqual(made["predicate"]["verifier"]["engineSha256"], sha256(engine_before.encode()))
        self.assertEqual(made["subject"][0]["digest"], {"gitCommit": tip})

    def test_without_the_label_a_harness_change_still_gets_no_statement(self):
        project = new_project(self)
        before, tip = self.push(project, lambda p: p.append("backbone/harness.conf", '\nHARNESS_REVIEW="off"\n'))
        runner, _ = take_engine(project, before)

        approval = self.approval_step(project, runner, before, [pull(merge=tip, labels=("bug",))])
        written = self.write(project, runner, before)

        self.assertEqual(approval.returncode, 0, approval.stdout + approval.stderr)
        self.assertNotIn("ATTEST_PULL_REQUEST", github_env(runner))
        self.assertIn("doesn't carry harness-change-approved", approval.stderr)
        self.assertEqual(written.returncode, 1)
        self.assertIn("user-only setting(s) changed", written.stderr)
        self.assertFalse((runner / STATEMENT_FILE).exists())

    def test_when_github_cant_be_read_the_push_is_unapproved_and_an_ordinary_push_still_gets_its_statement(self):
        project = new_project(self)
        before, _ = self.push(project, lambda p: p.write("docs/guide.md", "# Guide\n"))
        runner, _ = take_engine(project, before)

        approval = self.approval_step(project, runner, before, None)
        written = self.write(project, runner, before)

        self.assertEqual(approval.returncode, 0, approval.stdout + approval.stderr)
        self.assertIn("::warning::", approval.stdout)
        self.assertNotIn("ATTEST_PULL_REQUEST", github_env(runner))
        self.assertEqual(written.returncode, 0, written.stderr)
        made = json.loads((runner / STATEMENT_FILE).read_text())
        self.assertEqual((made["predicate"]["verification"]["allowUserChanges"],
                          made["predicate"]["verification"]["approval"]), (False, None))

    def test_the_step_reads_github_with_the_jobs_own_token_and_the_job_may_read_pull_requests(self):
        step, attest = step_text("attest", READ_APPROVAL), jobs()["attest"]

        self.assertIn("GH_TOKEN: ${{ github.token }}\n", step)
        self.assertIn("BRANCH: ${{ github.ref_name }}\n", step)
        self.assertIn('approval-check "$pulls" "$BEFORE..$GITHUB_SHA" "$BRANCH"', step)
        self.assertNotIn("secrets.", step)
        self.assertIn("    permissions:\n      contents: read\n      pull-requests: read\n", attest)
        self.assertNotIn("permissions:", jobs()["verify"])


def conf_lines(**settings):
    return "".join('\n%s="%s"\n' % (key, value) for key, value in settings.items())


class SigningProject(unittest.TestCase):
    """A project whose harness.conf can carry any signing settings, each at its own commit on the adopted one."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="signing ")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Project(Path(temp.name).resolve() / "project")
        cls.commits = {}

    def at(self, text):
        """A commit whose harness.conf is the adopted one plus text (made once per text)."""
        if not text:
            return self.project.adopted
        if text not in self.commits:
            self.project.git("checkout", "-q", "--detach", self.project.adopted)
            self.project.append("backbone/harness.conf", text)
            self.commits[text] = self.project.commit("chore: signing settings")
        return self.commits[text]

    def check(self, key=False, **settings):
        return self.project.harness("signing-check", self.at(conf_lines(**settings)), "true" if key else "false")

    def variables(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def assert_refused(self, result, reason):
        self.assertEqual((result.returncode, result.stdout), (1, ""), result.stderr)
        self.assertIn(reason, result.stderr)


class SigningCheck(SigningProject):
    """harness.py signing-check <commit> <key configured>: the signing mode the attest job uses, from harness.conf at
    the commit the push starts from. One signing source at a time, and keyless only when HARNESS_ATTEST_SIGNING says
    keyless."""

    def test_the_key_signs_by_default(self):
        self.assertEqual(self.variables(self.check(key=True)), {"ATTEST_MODE": "key"})
        self.assertEqual(self.variables(self.check(key=True, HARNESS_ATTEST_SIGNING="key")), {"ATTEST_MODE": "key"})

    def test_nothing_configured_or_key_signing_without_the_key_refuses(self):
        self.assert_refused(self.check(), "no signing is configured")
        self.assert_refused(self.check(HARNESS_ATTEST_SIGNING="key"), "no HARNESS_ATTEST_KEY")

    def test_a_kms_key_on_each_cloud_names_its_login(self):
        clouds = {
            "gcp": (GCP_KEY, GCP_PROVIDER + " " + GCP_ACCOUNT,
                    {"ATTEST_KMS_CLOUD": "gcp", "ATTEST_OIDC_AUDIENCE": "https://iam.googleapis.com/" + GCP_PROVIDER,
                     "ATTEST_GCP_PROVIDER": GCP_PROVIDER, "ATTEST_GCP_SERVICE_ACCOUNT": GCP_ACCOUNT}),
            "gcp, no impersonation": (GCP_KEY, GCP_PROVIDER, {
                "ATTEST_KMS_CLOUD": "gcp", "ATTEST_OIDC_AUDIENCE": "https://iam.googleapis.com/" + GCP_PROVIDER,
                "ATTEST_GCP_PROVIDER": GCP_PROVIDER, "ATTEST_GCP_SERVICE_ACCOUNT": ""}),
            "aws": (AWS_KEY, AWS_ROLE, {"ATTEST_KMS_CLOUD": "aws", "ATTEST_OIDC_AUDIENCE": "sts.amazonaws.com",
                                        "ATTEST_AWS_ROLE": AWS_ROLE, "ATTEST_AWS_REGION": "eu-west-1"}),
            "azure": (AZURE_KEY, AZURE_TENANT + " " + AZURE_CLIENT, {
                "ATTEST_KMS_CLOUD": "azure", "ATTEST_OIDC_AUDIENCE": "api://AzureADTokenExchange",
                "ATTEST_AZURE_TENANT": AZURE_TENANT, "ATTEST_AZURE_CLIENT": AZURE_CLIENT}),
            "vault": (VAULT_KEY, "https://vault.example.com harness-attest", {
                "ATTEST_KMS_CLOUD": "vault", "ATTEST_OIDC_AUDIENCE": "https://vault.example.com",
                "ATTEST_VAULT_ADDR": "https://vault.example.com", "ATTEST_VAULT_ROLE": "harness-attest"}),
        }
        for cloud, (key, identity, login) in clouds.items():
            with self.subTest(cloud=cloud):
                made = self.check(HARNESS_ATTEST_SIGNING="kms", HARNESS_ATTEST_KMS_KEY=key,
                                  HARNESS_ATTEST_KMS_IDENTITY=identity)

                self.assertEqual(self.variables(made), dict({"ATTEST_MODE": "kms", "ATTEST_KMS_KEY": key}, **login))

    def test_a_kms_key_needs_a_reference_and_an_identity_it_can_read(self):
        cases = {
            "no key": (dict(HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE), "HARNESS_ATTEST_KMS_KEY"),
            "a file, not a KMS": (dict(HARNESS_ATTEST_KMS_KEY="cosign.key", HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE),
                                  "is not a gcpkms://"),
            "an AWS alias without its ARN": (dict(HARNESS_ATTEST_KMS_KEY="awskms:///alias/attest",
                                                  HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE), "is not a gcpkms://"),
            "no identity": (dict(HARNESS_ATTEST_KMS_KEY=AWS_KEY), "HARNESS_ATTEST_KMS_IDENTITY for an aws key"),
            "another cloud's identity": (dict(HARNESS_ATTEST_KMS_KEY=GCP_KEY, HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE),
                                         "HARNESS_ATTEST_KMS_IDENTITY for a gcp key"),
            "a Vault without https": (dict(HARNESS_ATTEST_KMS_KEY=VAULT_KEY,
                                           HARNESS_ATTEST_KMS_IDENTITY="http://vault:8200 harness-attest"),
                                      "HARNESS_ATTEST_KMS_IDENTITY for a vault key"),
        }
        for case, (settings_, reason) in cases.items():
            with self.subTest(case=case):
                self.assert_refused(self.check(HARNESS_ATTEST_SIGNING="kms", **settings_), reason)

    def test_one_signing_source_at_a_time(self):
        kms = dict(HARNESS_ATTEST_KMS_KEY=AWS_KEY, HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE)
        self.assert_refused(self.check(key=True, HARNESS_ATTEST_SIGNING="kms", **kms), "HARNESS_ATTEST_KEY is set")
        self.assert_refused(self.check(key=True, HARNESS_ATTEST_SIGNING="keyless"), "HARNESS_ATTEST_KEY is set")
        self.assert_refused(self.check(key=True, **kms), "HARNESS_ATTEST_SIGNING is key:")
        self.assert_refused(self.check(**kms), "but HARNESS_ATTEST_SIGNING is key:")
        self.assert_refused(self.check(HARNESS_ATTEST_SIGNING="keyless", **kms), "HARNESS_ATTEST_SIGNING is keyless")

    def test_keyless_signs_only_when_harness_attest_signing_says_keyless(self):
        self.assertEqual(self.variables(self.check(HARNESS_ATTEST_SIGNING="keyless")), {"ATTEST_MODE": "keyless"})
        for value in ("Keyless", "yes", "true", "sigstore", ""):
            with self.subTest(value=value):
                self.assert_refused(self.check(HARNESS_ATTEST_SIGNING=value),
                                    "HARNESS_ATTEST_SIGNING is '%s'" % value)

    def test_the_settings_are_read_at_the_commit_given_not_from_the_checkout_or_the_environment(self):
        keyless = self.at(conf_lines(HARNESS_ATTEST_SIGNING="keyless"))
        self.project.git("checkout", "-q", "--detach", self.at(conf_lines(HARNESS_ATTEST_SIGNING="kms")))

        made = self.project.harness("signing-check", keyless, "false", HARNESS_ATTEST_SIGNING="key")
        default = self.project.harness("signing-check", self.project.adopted, "false",
                                       HARNESS_ATTEST_SIGNING="keyless")

        self.assertEqual(self.variables(made), {"ATTEST_MODE": "keyless"})
        self.assert_refused(default, "no signing is configured")

    def test_its_usage(self):
        for args in ((), ("HEAD",), ("HEAD", "yes"), ("HEAD", "true", "extra")):
            with self.subTest(args=args):
                result = self.project.harness("signing-check", *args)

                self.assertEqual((result.returncode, result.stdout), (64, ""))
                self.assertIn("usage: harness.py signing-check <commit> <true|false>", result.stderr)
        self.assert_refused(self.project.harness("signing-check", "no-such-commit", "true"),
                            "no-such-commit is not a commit")

    def test_the_signing_settings_are_user_only(self):
        project = new_project(self)
        for key, value in (("HARNESS_ATTEST_SIGNING", "keyless"), ("HARNESS_ATTEST_KMS_KEY", AWS_KEY),
                           ("HARNESS_ATTEST_KMS_IDENTITY", AWS_ROLE)):
            with self.subTest(key=key):
                project.git("reset", "-q", "--hard", project.adopted)
                project.append("backbone/harness.conf", conf_lines(**{key: value}))
                project.commit("chore: change the signing")

                verify = project.harness("verify", "--range", project.adopted + "..HEAD")

                self.assertEqual(verify.returncode, 1, verify.stdout)
                self.assertIn("user-only setting(s) changed in backbone/harness.conf: %s" % key, verify.stdout)


if given is not None:
    MODES = st.sampled_from([None, "key", "kms", "keyless", "Keyless", "", "sigstore", "true"])
    KMS_KEYS = st.sampled_from([None, "", GCP_KEY, AWS_KEY, AZURE_KEY, VAULT_KEY, "awskms:///alias/a", "cosign.key"])
    IDENTITIES = st.sampled_from([None, "", GCP_PROVIDER, AWS_ROLE, AZURE_TENANT + " " + AZURE_CLIENT, "garbage"])

    class SigningProperties(SigningProject):
        @settings(max_examples=examples(40), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(mode=MODES, kms_key=KMS_KEYS, identity=IDENTITIES, key=st.booleans())
        def test_a_mode_is_one_signing_source_and_keyless_is_only_ever_chosen_by_name(self, mode, kms_key, identity,
                                                                                    key):
            chosen = {name: value for name, value in (("HARNESS_ATTEST_SIGNING", mode),
                                                      ("HARNESS_ATTEST_KMS_KEY", kms_key),
                                                      ("HARNESS_ATTEST_KMS_IDENTITY", identity)) if value is not None}

            result = self.check(key=key, **chosen)

            self.assertEqual(result.returncode == 0, bool(result.stdout), result.stdout + result.stderr)
            if result.returncode:
                self.assertEqual(result.returncode, 1, result.stderr)
                return
            mode_chosen = self.variables(result)["ATTEST_MODE"]
            self.assertEqual(mode_chosen, mode or "key")
            self.assertEqual(key, mode_chosen == "key")
            if mode_chosen != "kms":
                self.assertFalse(kms_key or identity)


class FindProject(unittest.TestCase):
    """The attest job's first step: whether it has anything to sign with. It reads harness.conf at the commit the
    push starts from, without the engine (which isn't taken yet), and agrees with the engine on what is set."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="find ")
        cls.addClassCleanup(temp.cleanup)
        cls.project = Project(Path(temp.name).resolve() / "project")

    def find(self, before, key=False):
        runner = runner_folder(self.project)
        result = run_step(self.project, FIND_SETTINGS, runner, BEFORE=before, ATTEST_KEY_SET="true" if key else "false")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return github_env(runner).get("ATTEST") == "true"

    def commit_conf(self, text):
        self.project.git("checkout", "-q", "--detach", self.project.adopted)
        self.project.append("backbone/harness.conf", text)
        return self.project.commit("chore: signing settings")


class FindSettings(FindProject):
    def test_the_key_or_a_signing_setting_at_the_previous_tip_turns_the_job_on(self):
        keyless = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="keyless"))

        self.assertTrue(self.find(self.project.adopted, key=True))
        self.assertTrue(self.find(keyless))
        self.assertFalse(self.find(self.project.adopted))
        self.assertFalse(self.find("0" * 40))
        self.assertTrue(self.find("0" * 40, key=True))

    def test_a_push_cant_switch_its_own_signing_on(self):
        self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="keyless"))

        self.assertFalse(self.find(self.project.adopted))

    def test_a_commented_setting_is_not_set(self):
        self.assertFalse(self.find(self.commit_conf('\n# HARNESS_ATTEST_SIGNING="keyless"\n')))


if given is not None:
    LINE = st.tuples(st.sampled_from(["", " ", "\t", "#", "# ", "  #"]),
                     st.sampled_from(["HARNESS_ATTEST_SIGNING", "HARNESS_ATTEST_KMS_KEY", "HARNESS_ATTEST_KMS_IDENTITY",
                                      "HARNESS_REVIEW", "HARNESS_ATTEST_SIGNING_X", "XHARNESS_ATTEST_SIGNING"]),
                     st.sampled_from(["=", " = ", "\t=", " "]),
                     st.sampled_from(['"keyless"', "keyless", "''", '"kms"', ""]))

    class FindProperties(FindProject):
        @settings(max_examples=examples(30), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(lines=st.lists(LINE, max_size=3))
        def test_the_first_step_and_the_engine_agree_on_whether_a_signing_setting_is_there(self, lines):
            before = self.commit_conf("\n" + "".join("%s%s%s%s\n" % line for line in lines))

            engine = self.project.harness("signing-check", before, "false")

            self.assertEqual(self.find(before), "no signing is configured" not in engine.stderr, engine.stderr)


class OidcJob(FindProject):
    """Only kms and keyless signing need GitHub's OIDC token, so only their job, attest-oidc, may ask for one. A first
    job without the environment or its secrets reads the mode at the commit the push starts from, as the engine does,
    and picks attest or attest-oidc; the engine in the job it picks refuses the other job's modes."""

    def chosen(self, before):
        runner = runner_folder(self.project)
        result = run_step(self.project, CHOOSE_JOB, runner, BEFORE=before, GITHUB_OUTPUT=str(runner / "out"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return dict(line.split("=", 1) for line in (runner / "out").read_text().splitlines())["oidc"] == "true"

    def checked(self, before, job, key=False):
        runner = runner_folder(self.project)
        result = run_step(self.project, CHECK_SIGNING, runner, BEFORE=before, GITHUB_JOB=job,
                          ATTEST_KEY_SET="true" if key else "false", ENGINE_SCRIPT=str(self.project.engine))
        return result, github_env(runner)

    def test_only_kms_or_keyless_at_the_previous_tip_runs_the_job_with_an_oidc_token(self):
        kms = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="kms", HARNESS_ATTEST_KMS_KEY=AWS_KEY,
                                          HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE))
        keyless = self.commit_conf("\nHARNESS_ATTEST_SIGNING=keyless\n")
        key = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="key"))
        commented = self.commit_conf('\n# HARNESS_ATTEST_SIGNING="keyless"\n')
        overridden = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="keyless") + conf_lines(
            HARNESS_ATTEST_SIGNING="key"))

        self.assertEqual([self.chosen(c) for c in (kms, keyless)], [True, True])
        self.assertEqual([self.chosen(c) for c in (self.project.adopted, key, commented, overridden, "0" * 40)],
                         [False] * 5)

    def test_each_job_refuses_the_modes_of_the_other(self):
        keyless = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="keyless"))
        kms = self.commit_conf(conf_lines(HARNESS_ATTEST_SIGNING="kms", HARNESS_ATTEST_KMS_KEY=AWS_KEY,
                                          HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE))
        cases = {"key": (self.project.adopted, True, "attest"), "keyless": (keyless, False, "attest-oidc"),
                 "kms": (kms, False, "attest-oidc")}
        for mode, (before, key, job) in cases.items():
            other = "attest" if job == "attest-oidc" else "attest-oidc"
            with self.subTest(mode=mode):
                accepted, variables = self.checked(before, job, key)
                refused, nothing = self.checked(before, other, key)

                self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
                self.assertEqual(variables["ATTEST_MODE"], mode)
                self.assertEqual(refused.returncode, 1)
                self.assertIn("::error::", refused.stdout)
                self.assertNotIn("ATTEST_MODE", nothing)

    def test_the_key_job_gets_no_oidc_token_and_the_oidc_job_runs_the_same_steps(self):
        workflow, every = WORKFLOW.read_text(), jobs()
        key, oidc, choose = every["attest"], every["attest-oidc"], every["attest-route"]

        self.assertEqual(re.findall(r"^ *id-token:.*$", workflow, re.M), ["      id-token: write"])
        self.assertIn("    permissions:\n      contents: read\n      pull-requests: read\n    env:", key)
        self.assertIn("    permissions:\n      contents: read\n      pull-requests: read\n      id-token: write\n", oidc)
        self.assertIn("    needs: attest-route\n"
                      "    if: github.event_name == 'push' && needs.attest-route.outputs.oidc == 'false'\n", key)
        self.assertIn("    needs: attest-route\n"
                      "    if: github.event_name == 'push' && needs.attest-route.outputs.oidc == 'true'\n", oidc)
        for job in (key, oidc):
            self.assertIn("    environment: harness-attest\n", job)
        self.assertIn("    env: &attest-env\n", key)
        self.assertIn("    steps: &attest-steps\n", key)
        self.assertTrue(oidc.endswith("    env: *attest-env\n    steps: *attest-steps\n"), oidc)
        self.assertIn("    if: github.event_name == 'push'\n", choose)
        for word in ("environment:", "secrets.", "permissions:"):
            self.assertNotIn(word, choose)
        self.assertIn("      oidc: ${{ steps.choose.outputs.oidc }}\n", choose)
        self.assertIn("        id: choose\n", step_text("attest-route", CHOOSE_JOB))

    if given is not None:
        SIGNING_LINE = st.tuples(st.sampled_from(["", " ", "\t", "#"]),
                                 st.sampled_from(["HARNESS_ATTEST_SIGNING", "HARNESS_ATTEST_SIGNING_X"]),
                                 st.sampled_from(["=", " = ", "\t="]),
                                 st.sampled_from(["keyless", '"keyless"', "'kms'", "kms", '"key"', "key", "", "Kms",
                                                  '"keyless']))

        @settings(max_examples=examples(30), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(lines=st.lists(SIGNING_LINE, max_size=3), kms=st.booleans(), key=st.booleans())
        def test_the_first_job_and_the_engine_agree_on_whether_the_mode_needs_the_token(self, lines, kms, key):
            text = "\n" + "".join("%s%s%s%s\n" % line for line in lines)
            if kms:
                text += conf_lines(HARNESS_ATTEST_KMS_KEY=AWS_KEY, HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE)
            before = self.commit_conf(text)

            engine = self.project.harness("signing-check", before, "true" if key else "false")

            if engine.returncode == 0:
                self.assertEqual(self.chosen(before), "ATTEST_MODE=key\n" not in engine.stdout, engine.stdout)


class KmsLogin(unittest.TestCase):
    """The KMS login, in each step that uses the KMS key: it asks GitHub for the job's OIDC token with the audience the
    cloud trusts, and hands it to cosign's KMS client the way that cloud's SDK reads it, in that step alone: no later
    step (the statement, the export, the uploads) inherits a variable, and no token or credential file is left. The
    clouds aren't reached: a key file stands in for the reference, and the cosign the step runs records what it
    received before the real cosign signs."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="kms ")
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name).resolve()
        cls.project = Project(cls.work / "project")
        cls.tip = cls.project.finish("1.1", "Customer search", SEARCH)

    def setUp(self):
        self.cosign = cosign_or_skip(self)
        self.key = self.work / self._testMethodName
        self.public = key_pair(self, self.key, self.cosign, password="")[1]

    def sign(self, service, **login):
        """(the signing step's result, its runner, the call that signed, the token's audiences asked for)."""
        self.project.git("checkout", "-q", "--detach", self.tip)
        runner = runner_folder(self.project)
        recorder = recording_cosign(runner, self.cosign)
        (runner / "harness-attestation").mkdir()
        (runner / STATEMENT_FILE).write_text(self.project.harness("attest", "--range", self.project.adopted + "..HEAD",
                                                                  check=True).stdout)
        result = run_step(self.project, SIGN, runner, ATTEST_MODE="kms", ATTEST_KMS_KEY=str(self.key / "cosign.key"),
                          COSIGN_PASSWORD="", **dict(service.settings, **dict(recorder, **login)))
        signing = [c for c in recording_cosign_calls(runner) if c["args"][:1] == ["attest-blob"]]
        return result, runner, signing[0] if signing else None

    def assert_signed_and_nothing_left(self, result, runner, *secrets):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (runner / "check.pub").write_text(self.public)
        verified = run(self.work, self.cosign, "verify-blob-attestation", "--key", runner / "check.pub", "--bundle",
                       runner / BUNDLE_FILE, "--type", json.loads((runner / STATEMENT_FILE).read_text())["predicateType"],
                       "--digest", self.tip, "--digestAlg", "gitCommit", "--insecure-ignore-tlog", check=False)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertEqual(github_env(runner), {})
        self.assertEqual(left_in(runner, *secrets), [])

    def test_gcp_gets_a_workload_identity_credential_file(self):
        service = FakeTokenService(self)

        result, runner, signing = self.sign(service, ATTEST_KMS_CLOUD="gcp", ATTEST_GCP_PROVIDER=GCP_PROVIDER,
                                            ATTEST_GCP_SERVICE_ACCOUNT=GCP_ACCOUNT,
                                            ATTEST_OIDC_AUDIENCE="https://iam.googleapis.com/" + GCP_PROVIDER)

        self.assert_signed_and_nothing_left(result, runner, "a.github.oidc.token", "external_account")
        self.assertEqual(service.audiences, ["https://iam.googleapis.com/" + GCP_PROVIDER])
        credentials = json.loads(signing["files"]["GOOGLE_APPLICATION_CREDENTIALS"])
        self.assertEqual(credentials.pop("credential_source")["file"], str(runner / "harness-attest-oidc.jwt"))
        self.assertEqual(credentials, {
            "type": "external_account", "audience": "//iam.googleapis.com/" + GCP_PROVIDER,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "token_url": "https://sts.googleapis.com/v1/token",
            "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                                                 "%s:generateAccessToken" % GCP_ACCOUNT})

    def test_aws_and_azure_read_the_token_file_their_sdk_names(self):
        clouds = {
            "aws": (dict(ATTEST_KMS_CLOUD="aws", ATTEST_AWS_ROLE=AWS_ROLE, ATTEST_AWS_REGION="eu-west-1",
                         ATTEST_OIDC_AUDIENCE="sts.amazonaws.com"),
                    {"AWS_ROLE_ARN": AWS_ROLE, "AWS_REGION": "eu-west-1", "AWS_ROLE_SESSION_NAME": "harness-attest"},
                    "AWS_WEB_IDENTITY_TOKEN_FILE"),
            "azure": (dict(ATTEST_KMS_CLOUD="azure", ATTEST_AZURE_TENANT=AZURE_TENANT, ATTEST_AZURE_CLIENT=AZURE_CLIENT,
                           ATTEST_OIDC_AUDIENCE="api://AzureADTokenExchange"),
                      {"AZURE_TENANT_ID": AZURE_TENANT, "AZURE_CLIENT_ID": AZURE_CLIENT},
                      "AZURE_FEDERATED_TOKEN_FILE"),
        }
        for cloud, (login, expected, token_variable) in clouds.items():
            with self.subTest(cloud=cloud):
                service = FakeTokenService(self)

                result, runner, signing = self.sign(service, **login)

                self.assert_signed_and_nothing_left(result, runner, "a.github.oidc.token")
                self.assertEqual(service.audiences, [login["ATTEST_OIDC_AUDIENCE"]])
                self.assertEqual({k: signing["variables"][k] for k in expected}, expected)
                self.assertEqual(signing["files"][token_variable], "a.github.oidc.token")

    def test_vault_trades_the_token_for_a_masked_vault_token(self):
        service = FakeTokenService(self, vault_token="a-vault-token")
        address = service.settings["ACTIONS_ID_TOKEN_REQUEST_URL"].split("/token", 1)[0]

        result, runner, signing = self.sign(service, ATTEST_KMS_CLOUD="vault", ATTEST_VAULT_ADDR=address,
                                            ATTEST_VAULT_ROLE="harness-attest", ATTEST_OIDC_AUDIENCE=address)

        self.assert_signed_and_nothing_left(result, runner, "a.github.oidc.token", "a-vault-token")
        self.assertEqual(service.logins, [{"role": "harness-attest", "jwt": "a.github.oidc.token"}])
        self.assertIn("::add-mask::a-vault-token", result.stdout)
        self.assertEqual((signing["variables"]["VAULT_ADDR"], signing["variables"]["VAULT_TOKEN"]),
                         (address, "a-vault-token"))

    def test_no_token_no_login_and_a_failed_login_leaves_no_token(self):
        cases = {"no token": (FakeTokenService(self, answer='{"message": "no token"}'), {}),
                 "vault refuses": (FakeTokenService(self), dict(ATTEST_VAULT_ROLE="harness-attest"))}
        for case, (service, login) in cases.items():
            with self.subTest(case=case):
                address = service.settings["ACTIONS_ID_TOKEN_REQUEST_URL"].split("/token", 1)[0]
                cloud = dict(ATTEST_KMS_CLOUD="vault", ATTEST_VAULT_ADDR=address, ATTEST_OIDC_AUDIENCE=address) \
                    if login else dict(ATTEST_KMS_CLOUD="aws", ATTEST_AWS_ROLE=AWS_ROLE, ATTEST_AWS_REGION="eu-west-1",
                                       ATTEST_OIDC_AUDIENCE="sts.amazonaws.com")

                result, runner, signing = self.sign(service, **dict(cloud, **login))

                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(signing)
                self.assertFalse((runner / BUNDLE_FILE).exists())
                self.assertEqual(github_env(runner), {})
                self.assertEqual(left_in(runner, "a.github.oidc.token"), [])

    def test_each_step_that_uses_the_kms_key_logs_in_the_same_way(self):
        logins = [re.search(r"^kms_login\(\) \{\n.*?^\}\n", step_script(name), re.M | re.S)
                  for name in (CHECK_KEY, SIGN, SIGN_EXPORT)]

        self.assertTrue(all(logins), logins)
        self.assertEqual(len({login.group(0) for login in logins}), 1)
        self.assertNotIn("GITHUB_ENV", logins[0].group(0))


class SigningSteps(unittest.TestCase):
    """The attest job's key check and signing step in each mode, with cosign. A key file stands in for a KMS
    reference (cosign reads both through --key); the KMS itself and Sigstore's public services aren't reached."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="signing ")
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name).resolve()
        cls.project = Project(cls.work / "project")
        cls.tip = cls.project.finish("1.1", "Customer search", SEARCH)

    def setUp(self):
        self.cosign = cosign_or_skip(self)

    def runner(self):
        self.project.git("checkout", "-q", "--detach", self.tip)
        runner = runner_folder(self.project)
        (runner / "cosign").symlink_to(self.cosign)
        (runner / "harness-attestation").mkdir()
        (runner / STATEMENT_FILE).write_text(self.project.harness("attest", "--range", self.project.adopted + "..HEAD",
                                                                  check=True).stdout)
        return runner

    def sign(self, runner, **ci):
        return run_step(self.project, SIGN, runner, **ci)

    def verified(self, runner, public_key):
        (runner / "check.pub").write_text(public_key)
        commit = self.tip
        return run(self.work, self.cosign, "verify-blob-attestation", "--key", runner / "check.pub", "--bundle",
                   runner / BUNDLE_FILE, "--type", json.loads((runner / STATEMENT_FILE).read_text())["predicateType"],
                   "--digest", commit, "--digestAlg", "gitCommit", "--insecure-ignore-tlog", check=False)

    def test_the_key_mode_signs_with_the_environments_key(self):
        private, public = key_pair(self, self.work / "key", self.cosign)
        service = FakeTokenService(self)
        runner = self.runner()

        signed = self.sign(runner, ATTEST_MODE="key", HARNESS_ATTEST_KEY=private, COSIGN_PASSWORD="pw",
                           **service.settings)

        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        self.assertEqual(self.verified(runner, public).returncode, 0)
        self.assertEqual(service.audiences, [])

    def test_the_kms_mode_signs_with_the_reference_and_a_fresh_token(self):
        _, public = key_pair(self, self.work / "kms", self.cosign, password="")
        service = FakeTokenService(self)
        runner = self.runner()

        signed = self.sign(runner, ATTEST_MODE="kms", ATTEST_KMS_KEY=str(self.work / "kms" / "cosign.key"),
                           ATTEST_KMS_CLOUD="aws", ATTEST_AWS_ROLE=AWS_ROLE, ATTEST_AWS_REGION="eu-west-1",
                           ATTEST_OIDC_AUDIENCE="sts.amazonaws.com", COSIGN_PASSWORD="", **service.settings)

        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        self.assertEqual(service.audiences, ["sts.amazonaws.com"])
        self.assertEqual(self.verified(runner, public).returncode, 0)

    def test_the_kms_key_check_derives_the_public_key_from_the_reference(self):
        _, public = key_pair(self, self.work / "kms-check", self.cosign, password="")
        _, other = key_pair(self, self.work / "kms-other", self.cosign, password="")
        runner = self.runner()
        for published, accepted in ((public, True), (other, False)):
            with self.subTest(accepted=accepted):
                self.project.git("checkout", "-q", "--detach", self.project.adopted)
                self.project.write("harness-attest.pub", published)
                before = self.project.commit("chore: publish the attest public key")

                service = FakeTokenService(self)
                checked = run_step(self.project, CHECK_KEY, runner, ATTEST_MODE="kms", BEFORE=before,
                                   ATTEST_KMS_KEY=str(self.work / "kms-check" / "cosign.key"), COSIGN_PASSWORD="",
                                   ATTEST_KMS_CLOUD="aws", ATTEST_AWS_ROLE=AWS_ROLE, ATTEST_AWS_REGION="eu-west-1",
                                   ATTEST_OIDC_AUDIENCE="sts.amazonaws.com", **service.settings)

                self.assertEqual(checked.returncode == 0, accepted, checked.stdout + checked.stderr)
                self.assertEqual(service.audiences, ["sts.amazonaws.com"])
                self.assertEqual(left_in(runner, "a.github.oidc.token"), [])
                self.assertEqual(github_env(runner), {})
        self.project.git("checkout", "-q", "--detach", self.project.adopted)

    def test_a_kms_mode_without_a_reference_refuses_before_it_asks_for_a_token(self):
        service = FakeTokenService(self)
        runner = self.runner()

        signed = self.sign(runner, ATTEST_MODE="kms", ATTEST_KMS_KEY="", ATTEST_KMS_CLOUD="aws",
                           ATTEST_AWS_ROLE=AWS_ROLE, ATTEST_AWS_REGION="eu-west-1",
                           ATTEST_OIDC_AUDIENCE="sts.amazonaws.com", **service.settings)

        self.assertEqual(signed.returncode, 1, signed.stdout + signed.stderr)
        self.assertIn("::error::No KMS key reference", signed.stdout)
        self.assertEqual(service.audiences, [])
        self.assertFalse((runner / BUNDLE_FILE).exists())

    def test_the_key_and_kms_modes_never_fall_back_to_keyless(self):
        runner = self.runner()
        cases = {"kms without a reference": dict(ATTEST_MODE="kms", ATTEST_KMS_KEY=""),
                 "key without the secret": dict(ATTEST_MODE="key", HARNESS_ATTEST_KEY=""),
                 "no mode": dict(ATTEST_MODE=""), "an unknown mode": dict(ATTEST_MODE="sigstore")}
        for case, ci in cases.items():
            with self.subTest(case=case):
                signed = self.sign(runner, COSIGN_PASSWORD="", **ci)

                self.assertNotEqual(signed.returncode, 0, signed.stdout)
                self.assertFalse((runner / BUNDLE_FILE).exists())

    def test_only_the_keyless_branch_signs_without_a_key_and_only_it_uses_sigstores_services(self):
        branches = dict(re.findall(r"^  (\w+)\)\n((?:    .*\n)+?)    ;;", step_script(SIGN), re.M))

        for mode in ("key", "kms"):
            self.assertIn("--key", branches[mode])
            self.assertIn('--signing-config "$RUNNER_TEMP/signing-config.json"', branches[mode])
        self.assertNotIn("--key", branches["keyless"])
        self.assertNotIn("--signing-config", branches["keyless"])
        self.assertIn("attest-blob --yes --statement", branches["keyless"])


class CiProtectSigning(unittest.TestCase):
    def test_ci_protect_attest_states_the_signing_the_default_branch_sets(self):
        project = new_project(self)
        plans = {
            "key": ("", ["signing on main: key", "harness-attest.pub is not on main"], ["Rekor"]),
            "keyless": (conf_lines(HARNESS_ATTEST_SIGNING="keyless"), ["signing on main: keyless", "public Rekor log"],
                        ["harness-attest.pub is not on main"]),
            "kms": (conf_lines(HARNESS_ATTEST_SIGNING="kms", HARNESS_ATTEST_KMS_KEY=AWS_KEY,
                               HARNESS_ATTEST_KMS_IDENTITY=AWS_ROLE),
                    ["signing on main: kms: %s" % AWS_KEY, "harness-attest.pub is not on main"], ["Rekor"]),
            "invalid": (conf_lines(HARNESS_ATTEST_SIGNING="sigstore"), ["the job refuses to sign"], []),
        }
        for mode, (text, present, absent) in plans.items():
            with self.subTest(mode=mode):
                project.git("reset", "-q", "--hard", project.adopted)
                if text:
                    project.append("backbone/harness.conf", text)
                    project.commit("chore: signing settings")

                plan = project.harness("ci-protect", "--attest", "--dry-run")

                self.assertEqual(plan.returncode, 0, plan.stderr)
                for line in present:
                    self.assertIn(line, plan.stdout)
                for line in absent:
                    self.assertNotIn(line, plan.stdout)


if given is None:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
