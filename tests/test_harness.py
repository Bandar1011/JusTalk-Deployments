import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import harness as h

A = 'a' * 40
B = 'b' * 40
C = 'c' * 40
FILE = '20261013000000_initial.sql'
SECOND = '20261014000000_next.sql'


def active_policy():
    return {
        'source_repository': h.SOURCE, 'source_branch': 'production',
        'ci_workflow_path': '.github/workflows/database.yml',
        'production_project_ref': h.PROJECT,
        'baseline': {'source_sha': A, 'manifest_sha256': h.manifest({}), 'migration_count': 0},
        'activation_evidence': {'requester_id': 123, 'requester_login': 'requester[bot]',
                                'rehearsal_run_id': 456, 'protection_readback_sha256': 'd' * 64,
                                'capability_denial_evidence_sha256': 'e' * 64,
                                'owner_access_removal_evidence_sha256': 'f' * 64},
    }


class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('offline tests only'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.env = {'SOURCE_SHA': B, 'BASELINE_SHA': A, 'HARNESS_SHA': C, 'CI_RUN_ID': '42',
                    'GITHUB_REPOSITORY': h.DEPLOY, 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': C,
                    'GITHUB_ACTOR': 'requester[bot]', 'GITHUB_ACTOR_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}

    def test_missing_baseline_activation_and_foreign_target_fail_closed(self):
        variants = [dict(active_policy(), baseline=None), dict(active_policy(), activation_evidence=None),
                    dict(active_policy(), production_project_ref='different-project')]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'policy').mkdir()
            with patch.object(h, 'ROOT', root):
                for policy in variants:
                    (root / 'policy/production.json').write_text(json.dumps(policy))
                    with self.assertRaises(h.Stop):
                        h.load_policy()
                (root / 'policy/production.json').write_text(json.dumps(active_policy()))
                self.assertEqual(h.load_policy(), active_policy())

    def test_strict_revisions(self):
        for value in [None, '', 'HEAD', 'A' * 40, 'a' * 39, 'a' * 40 + '\n', 'a;curl']:
            with self.subTest(value=value), self.assertRaises(h.Stop):
                h.revision(value)
        self.assertEqual(h.revision(A), A)

    def test_manifest_rejects_paths_duplicate_versions_invalid_utf8(self):
        for files in [{'../' + FILE: b'x'}, {FILE: b'\xff'}, {'initial.sql': b'x'},
                      {FILE: b'a', '20261013000000_other.sql': b'b'}, {'nested/' + FILE: b'x'}]:
            with self.subTest(files=list(files)), self.assertRaises((h.Stop, UnicodeError)):
                h.manifest(files)

    def test_manifest_binds_names_and_bytes_and_is_stable(self):
        files = {SECOND: b'b', FILE: b'a'}
        self.assertEqual(h.manifest(files), h.manifest(dict(reversed(list(files.items())))))
        self.assertNotEqual(h.manifest(files), h.manifest({FILE: b'a\n', SECOND: b'b'}))

    def test_changed_deleted_and_backdated_history_fail(self):
        baseline = {FILE: b'create table old_fixture(id integer);'}
        for candidate in [{}, {FILE: b'changed'}, {**baseline, '20261012000000_earlier.sql': b'x'}]:
            with self.subTest(candidate=list(candidate)), self.assertRaises(h.Stop):
                h.append_only(baseline, candidate)
        h.append_only(baseline, {**baseline, SECOND: b'alter table old_fixture add value integer;'})

    def test_request_binds_three_revisions_actor_branch_and_reruns(self):
        with patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(h.request(active_policy()), (B, A, C, '42'))
        for key, value in [('BASELINE_SHA', B), ('HARNESS_SHA', A), ('GITHUB_REF', 'refs/heads/other'),
                           ('GITHUB_ACTOR', 'Bandar1011'), ('GITHUB_ACTOR_ID', '210632822'),
                           ('GITHUB_RUN_ATTEMPT', '2'), ('CI_RUN_ID', '0')]:
            with self.subTest(key=key), patch.dict(os.environ, {**self.env, key: value}, clear=True):
                with self.assertRaises(h.Stop):
                    h.request(active_policy())

    def test_source_tree_symlink_nested_and_non_sql_fail_without_blob_fetch(self):
        for path, mode, kind in [('supabase/migrations/' + FILE, '120000', 'blob'),
                                 ('supabase/migrations/nested/' + FILE, '100644', 'blob'),
                                 ('supabase/migrations/README.md', '100644', 'blob'),
                                 ('supabase', '120000', 'blob')]:
            tree = {'truncated': False, 'tree': [{'path': path, 'mode': mode, 'type': kind, 'sha': A}]}
            with self.subTest(path=path), patch.object(h, 'github', return_value=tree) as api:
                with self.assertRaises(h.Stop):
                    h.source_files(A, 'fake-token')
                self.assertEqual(api.call_count, 1)

    def test_source_tree_truncation_and_utf8_content(self):
        with patch.object(h, 'github', return_value={'truncated': True, 'tree': []}):
            with self.assertRaises(h.Stop):
                h.source_files(A, 'fake-token')
        tree = {'truncated': False, 'tree': [{'path': 'supabase/migrations/' + FILE,
                'mode': '100644', 'type': 'blob', 'sha': A}]}
        with patch.object(h, 'github', side_effect=[tree, {'encoding': 'base64', 'content': 'U0VMRUNUIDE7'}]):
            self.assertEqual(h.source_files(B, 'fake-token'), {FILE: b'SELECT 1;'})

    def test_ci_validates_exact_job_and_commit(self):
        run = {'head_sha': B, 'head_branch': 'production', 'event': 'push', 'status': 'completed',
               'conclusion': 'success', 'path': '.github/workflows/database.yml',
               'repository': {'full_name': h.SOURCE}, 'head_repository': {'full_name': h.SOURCE}}
        answers = [{'object': {'sha': B}}, run,
                   {'total_count': 1, 'jobs': [{'name': 'database', 'conclusion': 'success'}]},
                   {'status': 'ahead'}]
        with patch.object(h, 'github', side_effect=answers):
            h.validate_source(B, '42', 'fake', A)
        for field, value in [('head_sha', A), ('event', 'pull_request'), ('path', '.github/workflows/fake.yml')]:
            bad = copy.deepcopy(answers)
            bad[1][field] = value
            with self.subTest(field=field), patch.object(h, 'github', side_effect=bad):
                with self.assertRaises(h.Stop):
                    h.validate_source(B, '42', 'fake', A)
        bad = copy.deepcopy(answers)
        bad[2]['jobs'][0]['conclusion'] = 'skipped'
        with patch.object(h, 'github', side_effect=bad), self.assertRaises(h.Stop):
            h.validate_source(B, '42', 'fake', A)

    def test_private_subprocess_failure_does_not_leak_or_inherit_credentials(self):
        sentinel = 'PRIVATE_SQL_AND_PASSWORD_SENTINEL'
        script = "import os,sys;print('" + sentinel + "');print(os.getenv('SOURCE_READ_TOKEN'));sys.exit(9)"
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'SOURCE_READ_TOKEN': sentinel,
                'PRODUCTION_ACCESS_TOKEN': sentinel, 'PGPASSWORD': sentinel, 'SUPABASE_ACCESS_TOKEN': sentinel}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            with self.assertRaises(h.Stop):
                h.quiet([sys.executable, '-c', script], Path(temp))
            result = h.quiet([sys.executable, '-c', "import os;print(os.getenv('SOURCE_READ_TOKEN'));print(os.getenv('PGPASSWORD'));print(os.getenv('SUPABASE_ACCESS_TOKEN'))"], Path(temp))
        self.assertEqual(result, b'None\nNone\nNone\n')
        self.assertNotIn(sentinel, output.getvalue())

    def test_command_result_excludes_stderr_notices(self):
        output = io.StringIO()
        script = "import sys;print('2.120.0');print('CLI_UPDATE_NOTICE', file=sys.stderr)"
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(output):
            result = h.quiet([sys.executable, '-c', script], Path(temp))
        self.assertEqual(result.strip(), h.CLI_VERSION.encode())
        self.assertEqual(output.getvalue(), '')

    def test_main_suppresses_private_exception_tracebacks(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['harness.py', 'request']), \
                patch.object(h, 'load_policy', side_effect=RuntimeError('PRIVATE_SQL_SENTINEL')), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.assertEqual(h.main(), 1)
        self.assertEqual(output.getvalue(), 'BLOCKED\n')

    def test_http_errors_are_closed_without_echoing_private_messages(self):
        body = io.BytesIO(b'PRIVATE_SQL_SENTINEL')
        error = urllib.error.HTTPError('https://api.invalid', 401, 'PRIVATE_SQL_SENTINEL', {}, body)
        output = io.StringIO()
        with patch.object(h.urllib.request, 'build_opener') as opener, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            opener.return_value.open.side_effect = error
            with self.assertRaises(h.Stop):
                h.get_json('https://api.invalid', 'fake-token')
        self.assertTrue(body.closed)
        self.assertEqual(output.getvalue(), '')

    def test_http_response_limit_is_enforced(self):
        with patch.object(h, 'LIMIT', 64), patch.object(h.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(b' ' * 65)
            with self.assertRaises(h.Stop):
                h.get_json('https://api.invalid', 'fake-token')

    def test_no_redirect_can_forward_bearer(self):
        self.assertIsNone(h.NoRedirect().redirect_request(None, None, 302, 'redirect', {}, 'https://evil.invalid'))

    def test_remote_history_requires_exact_order_and_numeric_versions(self):
        for versions in [['20261014000000', '20261013000000'], ['bad'], ['20261013000000'] * 2]:
            responses = [[{'present': True}], [{'version': value} for value in versions]]
            with self.subTest(versions=versions), patch.object(h, 'get_json', side_effect=responses):
                with self.assertRaises(h.Stop):
                    h.history('fake')
        with patch.object(h, 'get_json', return_value=[{'present': False}]):
            self.assertEqual(h.history('fake'), [])

    def test_apply_history_mismatch_stops_before_link_or_push(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            root.mkdir(mode=0o700)
            work = h.workspace(root / 'database')
            h.write_files(work, {FILE: b'SELECT 1;'})
            proof = {'source_sha': B, 'baseline_sha': A, 'harness_sha': C, 'ci_run_id': '42',
                     'candidate_manifest': h.manifest({FILE: b'SELECT 1;'}),
                     'baseline_manifest': h.manifest({}), 'baseline_versions': [],
                     'candidate_versions': [FILE[:14]]}
            (root / 'proof.json').write_text(json.dumps(proof))
            with patch.object(h, 'private_root', return_value=root), \
                    patch.object(h, 'validate_source'), patch.object(h, 'secret', return_value='fake'), \
                    patch.object(h, 'history', return_value=['20261001000000']), patch.object(h, 'quiet') as cli:
                with self.assertRaises(h.Stop):
                    h.apply(active_policy(), (B, A, C, '42'))
                cli.assert_not_called()

    def test_replay_runs_upgrade_and_clean_checks_without_production_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            work = h.workspace(Path(temp) / 'database')
            with patch.object(h, 'quiet', return_value=b'') as cli:
                h.replay(work, {FILE: b'SELECT 1;'}, {FILE: b'SELECT 1;', SECOND: b'SELECT 2;'})
            commands = [call.args[0] for call in cli.call_args_list]
            self.assertEqual(commands[0], ['supabase', 'db', 'start'])
            self.assertEqual(commands.count(['supabase', 'db', 'reset', '--local', '--no-seed']), 2)
            self.assertEqual(commands.count(['supabase', 'db', 'lint', '--local', '--fail-on', 'warning']), 2)
            self.assertIn(['supabase', 'db', 'push', '--local', '--skip-vault'], commands)
            self.assertEqual(commands[-1], ['supabase', 'stop', '--no-backup'])
            self.assertTrue(all('extra_env' not in call.kwargs for call in cli.call_args_list))

    def test_workspace_only_materializes_validated_sql(self):
        with tempfile.TemporaryDirectory() as temp:
            work = h.workspace(Path(temp) / 'private')
            self.assertEqual(work.stat().st_mode & 0o777, 0o700)
            h.write_files(work, {FILE: b'SELECT 1;'})
            file = work / 'supabase/migrations' / FILE
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(file.read_bytes(), b'SELECT 1;')


if __name__ == '__main__':
    unittest.main()
