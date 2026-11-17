"""The no-merge profile (ADR-008, follow-up 10): the merge refusals of the `triple` profile, under a name that isn't
Triple's and without its catalog pack, for the agent software factory's lanes.

The rule is a decision table: a merge path is refused when harness.conf or the environment names a no-merge profile
(`triple` or `no-merge`), and the environment can add one but never lift the one harness.conf sets. The table is small,
so every row runs.
"""
import json
import os
import unittest

from factory_fixture import ROOT, Project

NO_MERGE = ("triple", "no-merge")
CONF_PROFILES = ("", "triple", "no-merge")
ENV_PROFILES = (None, "", "triple", "no-merge")
REFUSAL = "refused under HARNESS_PROFILE="


class Profiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project("no-merge profile ")
        cls.conf = cls.p.path / "backbone/harness.conf"
        cls.original = cls.conf.read_text()

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def tearDown(self):
        self.conf.write_text(self.original)

    def configure(self, conf_profile):
        self.conf.write_text(self.original + ('\nHARNESS_PROFILE="%s"\n' % conf_profile if conf_profile else ""))

    @staticmethod
    def env(env_profile):
        return {"HARNESS_PROFILE": env_profile} if env_profile is not None else {}

    def merge_paths(self, env):
        """Whether each merge path was refused."""
        mcp = {"session_id": "s1", "agent_id": "a1", "agent_type": "implementer",
               "tool_name": "mcp__github__merge_pull_request", "tool_input": {"pullNumber": 7}}
        return {
            "gh pr merge": self.p.bash("gh pr merge 7 --squash", "implementer", env=env).returncode == 2,
            "gh pr merge behind runners": self.p.bash("timeout -s KILL 60 nice -n 5 gh pr merge 7", "implementer",
                                                      env=env).returncode == 2,
            "gh pr merge after -R": self.p.bash("gh pr -R o/r merge 7", "implementer", env=env).returncode == 2,
            "merge API": self.p.bash("gh api -X PUT repos/o/r/pulls/7/merge", "implementer", env=env).returncode == 2,
            "merge tool": self.p.hook("pre-tool-use", mcp, env=env).returncode == 2,
            "orca --merge": REFUSAL in self.p.harness("orca", "--merge", check=False, env=env).stdout,
            "orca-nightly": REFUSAL in self.p.harness("orca-nightly", check=False, env=env).stdout,
        }

    def test_every_merge_path_is_refused_exactly_when_a_no_merge_profile_is_in_force(self):
        for conf_profile in CONF_PROFILES:
            self.configure(conf_profile)
            for env_profile in ENV_PROFILES:
                expected = conf_profile in NO_MERGE or env_profile in NO_MERGE
                with self.subTest(conf=conf_profile, env=env_profile):
                    refused = self.merge_paths(self.env(env_profile))

                    self.assertEqual(refused, dict.fromkeys(refused, expected))

    def test_the_refusal_names_the_profile_in_force(self):
        self.configure("no-merge")
        out = self.p.harness("orca", "--merge", "--trust", check=False).stdout
        denied = self.p.bash("gh pr merge 7", "implementer")

        self.assertIn("orca: --merge and --trust refused under HARNESS_PROFILE=no-merge", out)
        self.assertIn("Merging is refused under HARNESS_PROFILE=no-merge", denied.stderr)

    def test_session_start_tells_the_agent_only_a_human_merges(self):
        self.configure("no-merge")

        self.assertIn("PROFILE no-merge: only a human merges", self.p.hook("session-start", {}).stdout)

    def test_doctor_accepts_no_merge_and_names_it_for_an_unknown_profile(self):
        self.configure("no-merge")
        accepted = self.p.harness("doctor", check=False).stdout
        self.configure("bogus")
        rejected = self.p.harness("doctor", check=False).stdout

        self.assertNotIn("HARNESS_PROFILE must be", accepted)
        self.assertIn("HARNESS_PROFILE must be empty or one of triple|no-merge", rejected)

    def test_agents_may_not_set_or_lift_the_profile(self):
        self.configure("no-merge")
        edit = self.p.file_tool("Edit", "backbone/harness.conf", agent=None,
                                old_string='HARNESS_PROFILE="no-merge"', new_string='HARNESS_PROFILE=""')

        self.assertEqual(edit.returncode, 2, edit.stderr)
        self.assertIn("HARNESS_PROFILE may only be changed by the user", edit.stderr)


class Enroll(unittest.TestCase):
    """enroll --profile no-merge: the factory's lanes need harness-verify required (--protect), never an unattended
    merging schedule (--automation)."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project("no-merge enroll ")

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def enroll(self, *flags):
        return self.p.command(str(ROOT / "enroll.sh"), str(self.p.path), *flags, "--dry-run", check=False,
                              env={"HARNESS_ORCA_BIN": "/nonexistent/orca"})

    def test_no_merge_refuses_a_merging_schedule_before_changing_anything(self):
        result = self.enroll("--profile", "no-merge", "--orca", "--automation", "daily")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--automation refused under HARNESS_PROFILE=no-merge", result.stderr)
        self.assertNotIn("Enrolling", result.stdout)

    def test_no_merge_lets_the_user_require_the_harness_checks(self):
        result = self.enroll("--profile", "no-merge", "--protect")

        self.assertNotIn("refused", result.stderr)
        self.assertIn('HARNESS_PROFILE="no-merge"', result.stdout)

    def test_triple_still_refuses_both(self):
        result = self.enroll("--profile", "triple", "--protect")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--protect refused under HARNESS_PROFILE=triple", result.stderr)

    def test_an_unknown_profile_names_both(self):
        result = self.enroll("--profile", "bogus")

        self.assertEqual(result.returncode, 64)
        self.assertIn("known: triple, no-merge", result.stderr)


if __name__ == "__main__":
    unittest.main()
