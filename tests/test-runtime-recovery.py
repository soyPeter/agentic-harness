"""Task ordering and crash recovery at the shared runtime boundaries."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from factory_fixture import Project, ROOT

spec = importlib.util.spec_from_file_location('write_journal', ROOT / 'payload/owned/scripts/harness/lib/write_journal.py')
journal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journal)


class Dependencies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = Project('dependency runtime ')
        cls.p.add_task('9.3', 'Dependent')
        cls.p.add_task('9.2', 'Prerequisite')
        cls.p.write('backbone/3-TASKS.md', cls.p.read('backbone/3-TASKS.md').replace(
            '(spec: backbone/specs/9.3.md)', '(spec: backbone/specs/9.3.md) (after: 9.2)'))
        cls.p.write('backbone/specs/9.3.md', cls.p.spec_text('9.3'))
        cls.p.grill_pass('9.3')
        cls.p.write('backbone/specs/9.3.md', cls.p.read('backbone/specs/9.3.md') +
                    'Approved-by: fixture (2026-11-15)\n')

    @classmethod
    def tearDownClass(cls):
        cls.p.cleanup()

    def test_shared_selection_and_explicit_start(self):
        self.assertEqual(self.p.json('next', '--json')['task'], '9.2')
        step = self.p.json('next', '9.3', '--json')
        self.assertEqual(step['step'], 'blocked')
        self.assertEqual(step['dependencies'], ['9.2'])
        result = self.p.harness('start', '9.3', check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('waits for 9.2', result.stdout)
        self.p.set_marker('9.2', 'x')
        try:
            self.assertEqual(self.p.harness('start', '9.3').returncode, 0)
        finally:
            self.p.set_marker('9.2', ' ')
            self.p.set_marker('9.3', ' ')

    def test_agent_cannot_remove_dependency(self):
        before = self.p.read('backbone/3-TASKS.md')
        result = self.p.file_tool('Write', 'backbone/3-TASKS.md', agent=None, content=before.replace(' (after: 9.2)', ''))
        self.assertIn('Only the user may change', result.stdout + result.stderr)

    def test_warning_for_cycle_missing_and_started_early(self):
        before = self.p.read('backbone/3-TASKS.md')
        try:
            self.p.write('backbone/3-TASKS.md', before.replace('(spec: backbone/specs/9.2.md)',
                          '(spec: backbone/specs/9.2.md) (after: 9.3, 9.9)'))
            result = self.p.harness('spec-check', '9.3')
            self.assertIn('Dependency cycle: 9.3 -> 9.2 -> 9.3', result.stdout)
            self.assertIn('missing task 9.9', result.stdout)
        finally:
            self.p.write('backbone/3-TASKS.md', before)


class Writes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = journal.Journal(Path(self.temp.name) / 'writes.jsonl')

    def test_lost_reply_never_repeats_write_even_with_changed_intent(self):
        calls = []
        def accepted_then_lost():
            calls.append('accepted')
            raise TimeoutError('reply lost')
        with self.assertRaises(TimeoutError):
            self.store.execute('1', 'linear-comment', 'issue', 'body', accepted_then_lost)
        for intent in ('body', 'rephrased body'):
            with self.assertRaises(journal.IndeterminateWrite):
                self.store.execute('1', 'linear-comment', 'issue', intent, accepted_then_lost)
        self.assertEqual(calls, ['accepted'])
        self.assertEqual(len(self.store.pending()), 1)

    def test_known_success_is_reused_across_restarts(self):
        self.assertEqual(self.store.execute('1', 'issue-create', 'repo', 'intent', lambda: 'url'), 'url')
        restarted = journal.Journal(self.store.path)
        self.assertEqual(restarted.execute('1', 'issue-create', 'repo', 'intent',
                                          lambda: self.fail('duplicate write')), 'url')

    def test_attempt_fsync_failure_sends_nothing(self):
        with patch.object(journal.os, 'fsync', side_effect=OSError('disk failed')):
            with self.assertRaises(journal.IndeterminateWrite):
                self.store.execute('1', 'pr-edit', 'pr', 'intent', lambda: self.fail('write sent'))
        self.assertEqual(self.store.pending(), [])

    def test_failed_result_persistence_preserves_attempt(self):
        original = self.store.append
        def append(row):
            if row['state'] == 'observed':
                raise OSError('disk failed')
            original(row)
        with patch.object(self.store, 'append', side_effect=append):
            with self.assertRaises(journal.IndeterminateWrite):
                self.store.execute('1', 'pr-create', 'repo', 'intent', lambda: 'url')
        self.assertEqual(len(self.store.pending()), 1)

    def test_result_fsync_failure_retains_pending_attempt(self):
        key, _ = self.store.begin('1', 'pr-create', 'repo', 'intent')
        with patch.object(journal.os, 'fsync', side_effect=OSError('disk failed')):
            with self.assertRaises(journal.IndeterminateWrite):
                self.store.observe(key, 'url')
        self.assertEqual(len(self.store.pending()), 1)

    def test_corruption_fails_closed(self):
        self.store.path.write_text('{partial')
        with self.assertRaises(journal.IndeterminateWrite):
            self.store.execute('1', 'pr-create', 'repo', 'intent', lambda: self.fail('write sent'))

    def test_process_death_leaves_durable_attempt(self):
        code = '''import os, sys
sys.path.insert(0, sys.argv[1])
from write_journal import Journal
Journal(sys.argv[2]).execute('1', 'pr-create', 'repo', 'intent', lambda: os._exit(13))
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(Path(journal.__file__).parent), str(self.store.path)])
        self.assertEqual(result.returncode, 13)
        self.assertEqual(len(self.store.pending()), 1)

    def test_human_reconciliation_required_for_retry(self):
        key, _ = self.store.begin('1', 'pr-edit', 'pr', 'intent')
        self.store.resolve(key, 'verified absent; permit one retry', retry=True)
        self.assertEqual(self.store.execute('1', 'pr-edit', 'pr', 'intent', lambda: 'url'), 'url')
        self.assertEqual([json.loads(line)['state'] for line in self.store.path.read_text().splitlines()],
                         ['attempted', 'retry-authorized', 'attempted', 'observed'])


class ExternalWriteRecovery(unittest.TestCase):
    def test_linear_receipt_lost_reply_never_posts_twice(self):
        p = Project('linear lost reply ')
        self.addCleanup(p.cleanup)
        p.write('backbone/specs/1.1.md', 'Linear: DIS-142\n')
        code = """import sys
sys.path.insert(0, 'scripts/harness/lib')
import harness as h
import linear
h.receipt_data = lambda *args: ({}, None)
h.receipt_text = lambda data: 'fixture receipt'
linear.fetch_issue = lambda identifier: {'id': 'issue-uuid'}
calls = []
def post(issue, body):
    calls.append('accepted')
    raise linear.LinearError('reply lost')
linear.post_comment = post
for _ in range(2):
    try: h.linear_receipt('1.1', None, None, False)
    except h.HarnessError: pass
assert calls == ['accepted'], calls
assert len(h.write_journal_store().pending()) == 1
"""
        p.command('python3', '-B', '-c', code)

    def test_escalation_lost_reply_is_not_reissued(self):
        p = Project('escalation lost reply ')
        self.addCleanup(p.cleanup)
        p.add_task('1.1', 'Example')
        p.command('git', 'remote', 'add', 'origin', 'https://fixture-token@example.invalid/o/r.git')
        binary = p.base / 'bin'
        binary.mkdir()
        count = p.base / 'accepted'
        gh = binary / 'gh'
        gh.write_text('#!/bin/sh\nprintf accepted >> "' + str(count) + '"\nexit 1\n')
        gh.chmod(0o755)
        env = {'HARNESS_ESCALATE_GH': 'on', 'PATH': str(binary) + ':' + p.env['PATH']}
        for _ in range(2):
            result = p.harness('escalate', '1.1', '--kind', 'decision', '--reason', 'fixture',
                               check=False, env=env)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(count.read_text(), 'accepted')
        self.assertNotIn('fixture-token', p.read('.git/harness/writes.jsonl'))
        self.assertEqual(len(json.loads(p.harness('write-reconcile').stdout)), 1)


class HookRecovery(unittest.TestCase):
    def test_identical_pr_command_on_new_head_is_a_distinct_attempt(self):
        p = Project('write revision identity ')
        self.addCleanup(p.cleanup)
        data = {'session_id': 'fixture', 'tool_name': 'Bash',
                'tool_input': {'command': 'gh pr create --title example --body example'}}
        p.hook('pre-tool-use', data, check=True)
        p.hook('post-tool-use', dict(data, tool_response={'exit_code': 0}), check=True)
        p.commit('chore: next revision')
        p.hook('pre-tool-use', data, check=True)
        self.assertEqual(len(json.loads(p.harness('write-reconcile').stdout)), 1)

    def test_successful_single_write_is_observed_but_compound_failure_is_not(self):
        for command, expected in [('gh pr edit 7 --title example', 0),
                                  ('gh pr edit 7 --title example; true', 1)]:
            p = Project('write observation ')
            try:
                data = {'session_id': 'fixture', 'tool_name': 'Bash',
                        'tool_input': {'command': command}}
                p.hook('pre-tool-use', data, check=True)
                p.hook('post-tool-use', dict(data, tool_response={'exit_code': 0}), check=True)
                self.assertEqual(len(json.loads(p.harness('write-reconcile').stdout)), expected)
            finally:
                p.cleanup()

    def test_inline_journal_imports_are_refused(self):
        p = Project('journal import guard ')
        self.addCleanup(p.cleanup)
        for code in ('import write_journal', 'from write_journal import Journal',
                     'from importlib import import_module; import_module("write_journal")'):
            import shlex
            result = p.bash('python3 -c ' + shlex.quote(code))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_worktree_runner_preserves_dirty_work_on_indeterminate_write(self):
        p = Project('parked worktree ')
        self.addCleanup(p.cleanup)
        p.add_task('1.1', 'Example')
        p.commit('chore: fixture task')
        body = """printf dirty > unfinished.txt
python3 -B - <<'PYCODE'
import sys
sys.path.insert(0, 'scripts/harness/lib')
import harness as h
h.write_journal_store().begin('1.1', 'pr-create', 'repo', 'fixture')
PYCODE
exit 13
"""
        env = p.trust_agent('uncertain-worker.sh', body, HARNESS_VERIFY='block')
        result = p.harness('run', '--worktree', check=False, env=env)
        self.assertIn('retained worktree', result.stdout, result.stdout + result.stderr)
        trees = p.command('git', 'worktree', 'list', '--porcelain').stdout
        self.assertIn('harness/worktrees/1.1', trees)
        dirty = list(p.path.glob('.git/harness/worktrees/*/unfinished.txt'))
        self.assertEqual(len(dirty), 1, trees)
        self.assertEqual(dirty[0].read_text(), 'dirty')

    def test_unresolved_attempt_is_shared_with_linked_worktree(self):
        p = Project('shared write journal ')
        self.addCleanup(p.cleanup)
        p.add_task('1.1', 'Example')
        p.commit('chore: fixture task')
        tree = p.base / 'linked'
        p.command('git', 'worktree', 'add', '-q', '-b', 'linked', str(tree), 'HEAD')
        data = {'session_id': 'fixture', 'tool_name': 'Bash',
                'tool_input': {'command': 'gh pr create --title example --body example'}}
        p.hook('pre-tool-use', data, check=True)
        answer = p.command('python3', '-B', str(tree / 'scripts/harness/lib/harness.py'),
                           'next', '1.1', '--json', cwd=tree)
        self.assertEqual(json.loads(answer.stdout)['failure_class'], 'indeterminate_write')
        refused = p.bash('python3 scripts/harness/lib/harness.py write-reconcile key --observed evidence')
        self.assertIn('for the user', refused.stdout + refused.stderr)

    def test_unreported_pr_write_blocks_next_and_rephrased_retry(self):
        p = Project('unreported write ')
        self.addCleanup(p.cleanup)
        p.add_task('1.1', 'Example')
        data = {'session_id': 'fixture', 'tool_name': 'Bash',
                'tool_input': {'command': 'gh pr create --title example --body example'}}
        p.hook('pre-tool-use', data, check=True)
        pending = json.loads(p.harness('write-reconcile').stdout)
        self.assertEqual(len(pending), 1)
        self.assertEqual(p.json('next', '1.1', '--json')['failure_class'], 'indeterminate_write')
        data['tool_input']['command'] = 'gh pr create --title changed --body example'
        result = p.hook('pre-tool-use', data)
        self.assertIn('no retry', result.stdout + result.stderr)
        p.harness('write-reconcile', pending[0]['key'], '--observed', 'fixture confirmed PR fields')
        self.assertEqual(json.loads(p.harness('write-reconcile').stdout), [])


if __name__ == '__main__':
    unittest.main()
