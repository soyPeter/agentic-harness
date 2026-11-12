"""harness.py attest verify and attest policy (ADR-005 follow-ups 5 and 6): what a consumer runs on a signed verdict
statement. attest policy checks a statement (v1, or v0.1 as the engine wrote it before v1) against the consumer's
policy; attest verify first has cosign check the bundle's signature, then applies the policy to the statement the bundle
signs. The checks that run cosign skip without it. The property checks need hypothesis (pip install -r
tests/requirements.txt) and are skipped without it.
"""
import base64
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from attest_support import (HARNESS, PREDICATE_TYPE, PREDICATE_V01, SEARCH, SIGN, STATEMENT_FILE, BUNDLE_FILE, Project,
                            cosign_or_skip, key_pair, run, run_step, runner_folder)
from hypothesis_profiles import examples

try:
    from hypothesis import HealthCheck, given, settings, strategies as st
except ImportError:
    given = None


# Written by the v0.1 engine (the attest of commit dd2f9e9) for a project like FinishedTask's.
V01 = HARNESS / "tests/fixtures/attest/verdicts-v0.1.intoto.json"
V01_COMMIT = "73a321eb1c893dff925023457c02a093c015ed83"
V01_TREE = "32ccd100f43762ae5031f37d7cc024cf984b4426"
GATES = "HARNESS_JUDGE_GATE=on HARNESS_REVIEW=on HARNESS_SPEC_GATE=on"


class Statements(unittest.TestCase):
    """A v1 statement attest wrote for a finished task, and the v0.1 fixture, as files."""

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="attest verify ")
        cls.addClassCleanup(temp.cleanup)
        cls.work = Path(temp.name).resolve()
        cls.project = Project(cls.work / "project")
        cls.tip = cls.project.finish("1.1", "Customer search", SEARCH)
        cls.text = cls.project.harness("attest", "--range", cls.project.adopted + "..HEAD", check=True).stdout
        cls.v1 = json.loads(cls.text)
        cls.tree = cls.v1["subject"][1]["digest"]["gitTree"]
        cls.files = 0

    def file(self, statement):
        """statement (JSON, or text) as a file."""
        type(self).files += 1
        path = self.work / ("statement-%d.json" % self.files)
        path.write_text(statement if isinstance(statement, str) else json.dumps(statement, indent=2, sort_keys=True))
        return path

    def edited(self, change):
        """The v1 statement with change (a function of a copy of it) applied."""
        statement = json.loads(self.text)
        change(statement)
        return statement

    def policy(self, statement, *args, **settings_):
        return self.project.harness("attest", "policy", self.file(statement), *args, **settings_)

    def assert_accepted(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_refused(self, result, reason):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(reason, result.stdout)


class Policy(Statements):
    def test_a_v1_statement_of_the_commit_passes_the_default_policy(self):
        result = self.policy(self.v1, "--commit", self.tip)

        self.assert_accepted(result)
        self.assertIn("attest policy: no signature checked (attest verify checks it)", result.stdout)
        self.assertIn("attest policy: ok: %s, commit %s, verify PASSED, %s" % (PREDICATE_TYPE, self.tip, GATES),
                      result.stdout)

    def test_a_v01_statement_is_still_read(self):
        result = self.policy(V01.read_text(), "--commit", V01_COMMIT, "--tree", V01_TREE)

        self.assert_accepted(result)
        self.assertIn("ok: %s, commit %s, code %s" % (PREDICATE_V01, V01_COMMIT, V01_TREE), result.stdout)

    def test_the_code_subject_can_be_checked_instead_of_the_commit(self):
        self.assert_accepted(self.policy(self.v1, "--tree", self.tree))
        self.assert_refused(self.policy(self.v1, "--tree", "0" * 40), "no code subject is %s" % ("0" * 40))

    def test_another_commit_is_refused(self):
        other = self.project.adopted

        self.assert_refused(self.policy(self.v1, "--commit", other), "no commit subject is %s" % other)

    def test_a_policy_names_the_commit_or_the_code_it_checks(self):
        for args in ((), ("--commit",), ("--commit", "HEAD"), ("--commit", "abc123"), ("--tree", "main"),
                     ("--commit", self.tip, "--require", "HARNESS_REVIEW"), ("--commit", self.tip, "--frobnicate")):
            with self.subTest(args=args):
                result = self.policy(self.v1, *args)

                self.assertEqual((result.returncode, result.stdout), (64, ""))
                self.assertIn("usage: harness.py attest policy <statement>", result.stderr)

    def test_the_accepted_types_can_be_narrowed_to_v1(self):
        self.assert_refused(self.policy(V01.read_text(), "--commit", V01_COMMIT, "--type", PREDICATE_TYPE),
                            "the predicate type %s is not one the policy accepts" % PREDICATE_V01)
        self.assert_accepted(self.policy(self.v1, "--commit", self.tip, "--type", PREDICATE_TYPE))

    def test_what_isnt_a_verdict_statement_is_refused(self):
        cases = {
            "another statement type": (self.edited(lambda s: s.update(_type="https://in-toto.io/Statement/v0.1")),
                                       "not an in-toto Statement v1"),
            "another predicate": (self.edited(lambda s: s.update(predicateType="https://slsa.dev/provenance/v1")),
                                  "the predicate type https://slsa.dev/provenance/v1 is not one the policy accepts"),
            "not JSON": ("{not json", "doesn't parse"),
            "a list": ("[]", "not an in-toto Statement v1"),
            "no predicate": (self.edited(lambda s: s.pop("predicate")), "verify's result is missing"),
        }
        for case, (statement, reason) in cases.items():
            with self.subTest(case=case):
                self.assert_refused(self.policy(statement, "--commit", self.tip), reason)

    def test_fields_of_the_wrong_kind_are_refused_with_a_reason(self):
        cases = {
            "a predicate type that is not text": (self.edited(lambda s: s.update(predicateType=None)),
                                                  "the predicate type None is not one the policy accepts"),
            "an object as predicate type": (self.edited(lambda s: s.update(predicateType={"v": 1})),
                                            "is not one the policy accepts"),
            "allowUserChanges 1": (self.edited(lambda s: s["predicate"]["verification"].update(allowUserChanges=1)),
                                   "allowUserChanges is 1, not true or false"),
            "allowUserChanges 0": (self.edited(lambda s: s["predicate"]["verification"].update(allowUserChanges=0)),
                                   "allowUserChanges is 0, not true or false"),
        }
        for case, (statement, reason) in cases.items():
            with self.subTest(case=case):
                result = self.policy(statement, "--commit", self.tip)

                self.assert_refused(result, reason)
                self.assertNotIn("Traceback", result.stderr)

    def test_a_result_other_than_passed_is_refused(self):
        failed = self.edited(lambda s: s["predicate"]["verification"].update(result="FAILED"))

        self.assert_refused(self.policy(failed, "--commit", self.tip), "verify's result is FAILED, not PASSED")

    def test_the_gates_are_required_on_and_the_consumer_can_require_more_or_accept_a_gate_off(self):
        reviews_off = self.edited(lambda s: s["predicate"]["verification"]["settings"]["HARNESS_REVIEW"].update(
            value="off"))

        self.assert_refused(self.policy(reviews_off, "--commit", self.tip),
                            "HARNESS_REVIEW is 'off'; the policy requires 'on'")
        self.assert_accepted(self.policy(reviews_off, "--commit", self.tip, "--require", "HARNESS_REVIEW=off"))
        self.assert_refused(self.policy(self.v1, "--commit", self.tip, "--require", "HARNESS_TESTER=on"),
                            "HARNESS_TESTER is 'off'; the policy requires 'on'")
        self.assert_refused(self.policy(self.v1, "--commit", self.tip, "--require", "HARNESS_NO_SUCH=on"),
                            "HARNESS_NO_SUCH is missing; the policy requires 'on'")

    def test_a_range_verified_with_the_allow_flag_is_refused_unless_the_consumer_accepts_approved_changes(self):
        approved = self.edited(lambda s: s["predicate"]["verification"].update(
            allowUserChanges=True, approval={"label": "harness-change-approved", "pullRequest": 42}))
        by_hand = self.edited(lambda s: s["predicate"]["verification"].update(allowUserChanges=True))

        self.assert_refused(self.policy(approved, "--commit", self.tip),
                            "verified with --allow-user-changes (approved by pull request #42)")
        self.assert_refused(self.policy(by_hand, "--commit", self.tip),
                            "verified with --allow-user-changes (no approval recorded)")
        self.assert_accepted(self.policy(approved, "--commit", self.tip, "--accept-user-changes"))

    def test_attest_verify_says_so_when_cosign_is_not_installed(self):
        bundle = self.work / "bundle.json"
        bundle.write_text(json.dumps({"dsseEnvelope": {"payloadType": "application/vnd.in-toto+json",
                                                       "payload": base64.b64encode(self.text.encode()).decode()}}))

        tools = self.work / "no-cosign"
        tools.mkdir(exist_ok=True)
        for tool in ("python3", "git"):
            if not (tools / tool).exists():
                (tools / tool).symlink_to(shutil.which(tool))

        result = self.project.harness("attest", "verify", self.file(self.text), bundle, "--key", "k.pub",
                                      "--commit", self.tip, PATH=str(tools))

        self.assert_refused(result, "cosign is not installed")

    def test_attest_verify_takes_one_way_to_check_the_signer(self):
        for args in ((), ("--key", "k.pub", "--certificate-identity", "i", "--certificate-oidc-issuer", "o"),
                     ("--certificate-identity", "i"), ("--certificate-oidc-issuer", "o")):
            with self.subTest(args=args):
                result = self.project.harness("attest", "verify", "s.json", "b.json", *args, "--commit", self.tip)

                self.assertEqual((result.returncode, result.stdout), (64, ""))
                self.assertIn("usage: harness.py attest verify <statement> <bundle>", result.stderr)


if given is not None:
    CHECKED = st.sampled_from(["_type", "predicateType", "commit", "code", "result", "HARNESS_SPEC_GATE",
                               "HARNESS_JUDGE_GATE", "HARNESS_REVIEW", "allowUserChanges"])

    class PolicyProperties(Statements):
        @settings(max_examples=examples(24), deadline=None, suppress_health_check=[HealthCheck.too_slow])
        @given(field=CHECKED, value=st.one_of(st.text(min_size=1, max_size=8), st.booleans(), st.none(),
                                              st.integers(-2, 2)))
        def test_changing_any_field_the_policy_checks_turns_acceptance_into_refusal(self, field, value):
            def change(statement):
                verification = statement["predicate"]["verification"]
                if field in ("_type", "predicateType"):
                    statement[field] = value
                elif field in ("commit", "code"):
                    subject = statement["subject"][0 if field == "commit" else 1]["digest"]
                    subject[next(iter(subject))] = value
                elif field.startswith("HARNESS_"):
                    verification["settings"][field]["value"] = value
                else:
                    verification[field] = value
            original = json.loads(self.text)
            changed = self.edited(change)
            if changed == original or (field == "allowUserChanges" and value is False):
                return

            result = self.policy(changed, "--commit", self.tip, "--tree", self.tree)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


class Verify(Statements):
    """attest verify on a bundle the attest job's signing step made, with cosign."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.signed = {}

    def setUp(self):
        self.cosign = cosign_or_skip(self)

    def sign(self, text, name="key"):
        """(statement file, bundle file, public key file): text signed by the attest job's signing step with a key
        of its own (made once per name)."""
        if name not in self.signed:
            private, public = key_pair(self, self.work / ("keys-" + name), self.cosign)
            self.signed[name] = (private, public)
        private, public = self.signed[name]
        runner = runner_folder(self.project)
        (runner / "cosign").symlink_to(self.cosign)
        (runner / "harness-attestation").mkdir()
        (runner / STATEMENT_FILE).write_text(text)
        (runner / "key.pub").write_text(public)
        signed = run_step(self.project, SIGN, runner, ATTEST_MODE="key", HARNESS_ATTEST_KEY=private,
                          COSIGN_PASSWORD="pw")
        self.assertEqual(signed.returncode, 0, signed.stdout + signed.stderr)
        return runner / STATEMENT_FILE, runner / BUNDLE_FILE, runner / "key.pub"

    def verify(self, statement, bundle, key, *policy):
        return self.project.harness("attest", "verify", statement, bundle, "--key", key, *policy)

    def test_a_signed_statement_of_the_commit_verifies(self):
        statement, bundle, key = self.sign(self.text)

        result = self.verify(statement, bundle, key, "--commit", self.tip)

        self.assert_accepted(result)
        self.assertIn("attest verify: signature: ok (cosign, key %s)" % key, result.stdout)
        self.assertIn("attest verify: ok: %s, commit %s, verify PASSED, %s" % (PREDICATE_TYPE, self.tip, GATES),
                      result.stdout)

    def test_a_signed_v01_statement_still_verifies(self):
        statement, bundle, key = self.sign(V01.read_text())

        self.assert_accepted(self.verify(statement, bundle, key, "--commit", V01_COMMIT))

    def test_the_code_subject_alone_is_enough_to_check_the_signature(self):
        statement, bundle, key = self.sign(self.text)

        self.assert_accepted(self.verify(statement, bundle, key, "--tree", self.tree))

    def test_another_key_is_refused(self):
        statement, bundle, _ = self.sign(self.text)
        _, _, other = self.sign(self.text, name="other")

        result = self.verify(statement, bundle, other, "--commit", self.tip)

        self.assert_refused(result, "attest verify: the signature doesn't verify")

    def test_another_commit_is_refused_by_the_signature_check(self):
        statement, bundle, key = self.sign(self.text)

        self.assert_refused(self.verify(statement, bundle, key, "--commit", self.project.adopted),
                            "the signature doesn't verify")

    def test_a_statement_file_that_is_not_the_signed_statement_is_refused(self):
        statement, bundle, key = self.sign(self.text)
        statement.write_text(json.dumps(self.edited(lambda s: s["predicate"]["tasks"].clear())))

        self.assert_refused(self.verify(statement, bundle, key, "--commit", self.tip),
                            "the statement is not the one the bundle signs")

    def test_a_signed_payload_that_was_edited_is_refused(self):
        statement, bundle, key = self.sign(self.text)
        edited = self.edited(lambda s: s["predicate"]["verification"].update(allowUserChanges=False, result="PASSED"))
        edited["predicate"]["tasks"] = []
        data = json.loads(bundle.read_text())
        data["dsseEnvelope"]["payload"] = base64.b64encode(json.dumps(edited).encode()).decode()
        bundle.write_text(json.dumps(data))
        statement.write_text(json.dumps(edited))

        self.assert_refused(self.verify(statement, bundle, key, "--commit", self.tip), "the signature doesn't verify")

    def test_a_good_signature_on_a_statement_the_policy_refuses_is_refused(self):
        reviews_off = json.dumps(self.edited(
            lambda s: s["predicate"]["verification"]["settings"]["HARNESS_REVIEW"].update(value="off")))
        statement, bundle, key = self.sign(reviews_off)

        result = self.verify(statement, bundle, key, "--commit", self.tip)

        self.assert_refused(result, "HARNESS_REVIEW is 'off'; the policy requires 'on'")
        self.assertIn("signature: ok", result.stdout)

    def test_a_file_that_is_not_a_bundle_is_refused(self):
        statement, _, key = self.sign(self.text)
        for text in ("{not json", "{}", json.dumps({"dsseEnvelope": {"payloadType": "text/plain", "payload": ""}})):
            with self.subTest(text=text):
                bundle = self.work / "not-a-bundle.json"
                bundle.write_text(text)

                self.assert_refused(self.verify(statement, bundle, key, "--commit", self.tip),
                                    "is not a Sigstore bundle of an in-toto statement")


if given is None:
    print("skipped the property checks: hypothesis is not installed (pip install -r tests/requirements.txt)")


if __name__ == "__main__":
    unittest.main()
