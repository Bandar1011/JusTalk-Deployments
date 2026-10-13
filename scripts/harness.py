#!/usr/bin/env python3
"""Trusted migration harness. Private input never becomes public diagnostic output."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = 'Bandar1011/English-Learning-App'
DEPLOY = 'Bandar1011/JusTalk-Deployments'
PROJECT = 'huwtbhaxcrdgzlptvzop'
CLI_VERSION = '2.120.0'
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
MIGRATION = re.compile(r'([0-9]{14})_[a-z0-9_]+\.sql\Z')
LIMIT = 32 * 1024 * 1024


class Stop(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def need(condition):
    if not condition:
        raise Stop()


def revision(value):
    need(isinstance(value, str) and SHA.fullmatch(value))
    return value


def digest(value):
    need(isinstance(value, str) and DIGEST.fullmatch(value))
    return value


def get_json(url, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'JusTalk-Deployments',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            raw = response.read(LIMIT + 1)
            need(len(raw) <= LIMIT)
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        error.close()
        raise Stop() from None
    except (urllib.error.URLError, UnicodeError, json.JSONDecodeError):
        raise Stop() from None


def github(path, token):
    return get_json('https://api.github.com/repos/' + SOURCE + '/' + path, token)


def secret(name):
    value = os.environ.get(name, '')
    need(bool(value))
    return value


def manifest(files):
    versions = set()
    records = []
    for name, content in sorted(files.items()):
        match = MIGRATION.fullmatch(name)
        need(match is not None and match[1] not in versions)
        need(isinstance(content, bytes) and len(content) <= LIMIT)
        content.decode('utf-8')
        versions.add(match[1])
        records.append([name, hashlib.sha256(content).hexdigest()])
    encoded = json.dumps(records, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def append_only(baseline, candidate):
    manifest(baseline)
    manifest(candidate)
    for name, content in baseline.items():
        need(candidate.get(name) == content)
    if baseline:
        last = max(name[:14] for name in baseline)
        need(all(name[:14] > last for name in candidate.keys() - baseline.keys()))


def source_files(sha, token):
    tree = github('git/trees/' + revision(sha) + '?recursive=1', token)
    need(tree.get('truncated') is False and isinstance(tree.get('tree'), list))
    result = {}
    total = 0
    for item in tree['tree']:
        path = item.get('path', '')
        if path in {'supabase', 'supabase/migrations'}:
            need(item.get('type') == 'tree' and item.get('mode') == '040000')
        if not path.startswith('supabase/migrations/'):
            continue
        name = path.removeprefix('supabase/migrations/')
        need(PurePosixPath(name).name == name and MIGRATION.fullmatch(name))
        need(item.get('type') == 'blob' and item.get('mode') == '100644')
        blob = github('git/blobs/' + revision(item.get('sha')), token)
        need(blob.get('encoding') == 'base64' and isinstance(blob.get('content'), str))
        content = base64.b64decode(blob['content'].replace('\n', ''), validate=True)
        total += len(content)
        need(total <= LIMIT and name not in result)
        result[name] = content
    manifest(result)
    return result


def load_policy():
    policy = json.loads((ROOT / 'policy/production.json').read_text())
    need(policy.get('source_repository') == SOURCE)
    need(policy.get('source_branch') == 'production')
    need(policy.get('ci_workflow_path') == '.github/workflows/database.yml')
    need(policy.get('production_project_ref') == PROJECT)
    baseline = policy.get('baseline')
    need(isinstance(baseline, dict))
    revision(baseline.get('source_sha'))
    digest(baseline.get('manifest_sha256'))
    need(type(baseline.get('migration_count')) is int and baseline['migration_count'] >= 0)
    activation = policy.get('activation_evidence')
    need(isinstance(activation, dict))
    need(type(activation.get('requester_id')) is int and activation['requester_id'] > 0)
    need(isinstance(activation.get('requester_login'), str) and activation['requester_login'].endswith('[bot]'))
    need(type(activation.get('rehearsal_run_id')) is int and activation['rehearsal_run_id'] > 0)
    digest(activation.get('protection_readback_sha256'))
    digest(activation.get('capability_denial_evidence_sha256'))
    digest(activation.get('owner_access_removal_evidence_sha256'))
    return policy


def request(policy):
    source = revision(os.environ.get('SOURCE_SHA'))
    baseline = revision(os.environ.get('BASELINE_SHA'))
    harness = revision(os.environ.get('HARNESS_SHA'))
    need(baseline == policy['baseline']['source_sha'])
    need(os.environ.get('GITHUB_REPOSITORY') == DEPLOY)
    need(os.environ.get('GITHUB_REF') == 'refs/heads/main')
    need(harness == os.environ.get('GITHUB_SHA'))
    need(os.environ.get('GITHUB_ACTOR') == policy['activation_evidence']['requester_login'])
    need(os.environ.get('GITHUB_ACTOR_ID') == str(policy['activation_evidence']['requester_id']))
    need(os.environ.get('GITHUB_RUN_ATTEMPT') == '1')
    ci = os.environ.get('CI_RUN_ID', '')
    need(re.fullmatch(r'[1-9][0-9]{0,19}', ci) is not None)
    return source, baseline, harness, ci


def validate_source(source, ci, token, baseline=None):
    head = github('git/ref/heads/production', token)
    need(head.get('object', {}).get('sha') == source)
    run = github('actions/runs/' + ci, token)
    need(run.get('head_sha') == source and run.get('head_branch') == 'production')
    need(run.get('event') == 'push' and run.get('status') == 'completed')
    need(run.get('conclusion') == 'success' and run.get('path') == '.github/workflows/database.yml')
    need(run.get('repository', {}).get('full_name') == SOURCE)
    need(run.get('head_repository', {}).get('full_name') == SOURCE)
    jobs = github('actions/runs/' + ci + '/jobs?per_page=100', token)
    need(jobs.get('total_count', 101) <= 100)
    matching = [job for job in jobs.get('jobs', []) if job.get('name') == 'database']
    need(len(matching) == 1 and matching[0].get('conclusion') == 'success')
    if baseline is not None:
        comparison = github('compare/' + revision(baseline) + '...' + source, token)
        need(comparison.get('status') in {'ahead', 'identical'})


def public_line(status):
    need(status in {'REQUEST_VALIDATED', 'REPLAY_PASSED', 'DEPLOYMENT_VERIFIED', 'BLOCKED'})
    print(status, flush=True)


def quiet(command, cwd, *, extra_env=None):
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('SUPABASE_', 'PG', 'INPUT_'))
                   and key not in {'DATABASE_URL', 'DB_URL', 'SOURCE_READ_TOKEN', 'PRODUCTION_ACCESS_TOKEN',
                                   'PRODUCTION_DB_PASSWORD', 'GITHUB_TOKEN', 'GH_TOKEN'}}
    environment.update(extra_env or {})
    with tempfile.TemporaryFile() as output:
        completed = subprocess.run(command, cwd=cwd, env=environment, stdout=output,
                                   stderr=output, timeout=1800, check=False)
        output.seek(0)
        raw = output.read(LIMIT + 1)
        need(len(raw) <= LIMIT)
        need(completed.returncode == 0)
        return raw


def write_files(work, files):
    manifest(files)
    target = work / 'supabase/migrations'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, mode=0o700)
    for name, content in files.items():
        path = target / name
        path.write_bytes(content)
        path.chmod(0o600)


def workspace(root):
    need(not root.exists())
    root.mkdir(mode=0o700)
    (root / 'supabase').mkdir(mode=0o700)
    (root / 'supabase/config.toml').write_text('''project_id = "justalk-deployment-validation"
[db]
port = 54322
shadow_port = 54320
major_version = 17
[db.seed]
enabled = false
[analytics]
enabled = false
''')
    return root


def replay(work, baseline, candidate):
    write_files(work, baseline)
    quiet(['supabase', 'db', 'start'], work)
    try:
        quiet(['supabase', 'db', 'reset', '--local', '--no-seed'], work)
        write_files(work, candidate)
        quiet(['supabase', 'db', 'push', '--local', '--skip-vault'], work)
        quiet(['supabase', 'db', 'lint', '--local', '--fail-on', 'warning'], work)
        quiet(['supabase', 'test', 'db', '--local', str(ROOT / 'tests/smoke.sql')], work)
        quiet(['supabase', 'db', 'reset', '--local', '--no-seed'], work)
        quiet(['supabase', 'db', 'lint', '--local', '--fail-on', 'warning'], work)
        quiet(['supabase', 'test', 'db', '--local', str(ROOT / 'tests/smoke.sql')], work)
    finally:
        quiet(['supabase', 'stop', '--no-backup'], work)


def private_root():
    runner = Path(secret('RUNNER_TEMP'))
    need(runner.is_absolute())
    path = runner / 'justalk-private-deployment'
    need(not path.is_symlink())
    return path


def prepare(policy, values):
    source, baseline_sha, harness, ci = values
    token = secret('SOURCE_READ_TOKEN')
    validate_source(source, ci, token, baseline_sha)
    baseline = source_files(baseline_sha, token)
    candidate = source_files(source, token)
    expected = policy['baseline']
    need(manifest(baseline) == expected['manifest_sha256'])
    need(len(baseline) == expected['migration_count'])
    append_only(baseline, candidate)
    root = private_root()
    root.mkdir(mode=0o700)
    work = workspace(root / 'database')
    need(quiet(['supabase', '--version'], work).strip() == CLI_VERSION.encode())
    replay(work, baseline, candidate)
    proof = {'source_sha': source, 'baseline_sha': baseline_sha, 'harness_sha': harness,
             'ci_run_id': ci, 'baseline_manifest': manifest(baseline),
             'candidate_manifest': manifest(candidate), 'baseline_versions': sorted(x[:14] for x in baseline),
             'candidate_versions': sorted(x[:14] for x in candidate)}
    (root / 'proof.json').write_text(json.dumps(proof))
    (root / 'proof.json').chmod(0o600)
    public_line('REPLAY_PASSED')
    print('source=' + source + ' harness=' + harness + ' manifest=' + manifest(candidate)
          + ' migrations=' + str(len(candidate)))


def history(token):
    url = 'https://api.supabase.com/v1/projects/' + PROJECT + '/database/query/read-only'
    exists = get_json(url, token, {'query': "SELECT to_regclass('supabase_migrations.schema_migrations') IS NOT NULL AS present"})
    need(isinstance(exists, list) and len(exists) == 1 and type(exists[0].get('present')) is bool)
    if not exists[0]['present']:
        return []
    rows = get_json(url, token, {'query': 'SELECT version FROM supabase_migrations.schema_migrations ORDER BY version'})
    need(isinstance(rows, list))
    versions = [row.get('version') for row in rows]
    need(all(isinstance(v, str) and re.fullmatch(r'[0-9]{14}', v) for v in versions))
    need(versions == sorted(set(versions)))
    return versions


def apply(policy, values):
    source, baseline, harness, ci = values
    validate_source(source, ci, secret('SOURCE_READ_TOKEN'), baseline)
    root = private_root()
    need(root.is_dir() and root.stat().st_mode & 0o777 == 0o700)
    proof = json.loads((root / 'proof.json').read_text())
    need([proof[k] for k in ['source_sha', 'baseline_sha', 'harness_sha', 'ci_run_id']]
         == [source, baseline, harness, ci])
    validated = root / 'database'
    files = {}
    for path in (validated / 'supabase/migrations').iterdir():
        need(path.is_file() and not path.is_symlink())
        files[path.name] = path.read_bytes()
    need(manifest(files) == proof['candidate_manifest'])
    need(proof['baseline_manifest'] == policy['baseline']['manifest_sha256'])
    token = secret('PRODUCTION_ACCESS_TOKEN')
    password = secret('PRODUCTION_DB_PASSWORD')
    need(history(token) == proof['baseline_versions'])
    work = workspace(root / 'production')
    write_files(work, files)
    credentials = {'SUPABASE_ACCESS_TOKEN': token, 'SUPABASE_DB_PASSWORD': password}
    quiet(['supabase', 'link', '--project-ref', PROJECT, '--yes'], work, extra_env=credentials)
    linked = work / 'supabase/.temp/project-ref'
    need(linked.read_text().strip() == PROJECT)
    quiet(['supabase', 'db', 'push', '--linked', '--dry-run', '--skip-vault', '--yes'], work, extra_env=credentials)
    need(history(token) == proof['baseline_versions'])
    validate_source(source, ci, secret('SOURCE_READ_TOKEN'), baseline)
    quiet(['supabase', 'db', 'push', '--linked', '--skip-vault', '--yes'], work, extra_env=credentials)
    need(history(token) == proof['candidate_versions'])
    public_line('DEPLOYMENT_VERIFIED')
    print('source=' + source + ' harness=' + harness + ' manifest=' + proof['candidate_manifest']
          + ' migrations=' + str(len(files)))


def main():
    os.umask(0o077)
    try:
        need(len(sys.argv) == 2 and sys.argv[1] in {'request', 'prepare', 'apply', 'cleanup'})
        if sys.argv[1] == 'cleanup':
            root = private_root()
            if root.exists():
                shutil.rmtree(root)
            return 0
        policy = load_policy()
        values = request(policy)
        if sys.argv[1] == 'request':
            public_line('REQUEST_VALIDATED')
        elif sys.argv[1] == 'prepare':
            prepare(policy, values)
        else:
            apply(policy, values)
        return 0
    except Exception:
        public_line('BLOCKED')
        return 1


if __name__ == '__main__':
    sys.exit(main())
