# JusTalk database deployments

This public repository holds deployment tooling. JusTalk's source and SQL stay in the private `Bandar1011/English-Learning-App` repository. Production is Supabase project `huwtbhaxcrdgzlptvzop`. Development and staging use a different project.

**Deployment is inactive.** `policy/production.json` has no deployed baseline or activation evidence. Requests stop before the protected job. No production credentials should be installed until the actual approval gate and restricted requester have passed a no-secret rehearsal.

## Request and approval

After activation, dispatch `Deploy production database` on `main` with four explicit values.

| Input | Required value |
| --- | --- |
| `source_sha` | Full immutable commit SHA at the private app's `production` branch head |
| `baseline_sha` | Previously deployed full source SHA in the reviewed policy |
| `harness_sha` | Full public `main` commit SHA whose tooling the human reviewed |
| `ci_run_id` | Successful private `Database validation` push run for that exact production SHA |

The request must originate from the separately restricted GitHub App recorded in policy. Reruns are rejected. A changed commit or harness needs a fresh request and approval. The app still follows development, staging, then production promotion. This workflow never promotes branches.

The protected job names both source and harness revisions. Bandar must review the private PR, SQL changes, schema impact and test evidence before approving that exact job. The deployment queue is serialized and never cancels an active migration.

After approval, the harness fetches only migration blobs for the exact source and baseline revisions. It verifies the private production head, successful expected workflow and `database` job, baseline ancestry, historical checksums and ordered additions. Candidate scripts, workflow definitions, seeds, tests and Supabase configuration are never executed by this harness. The harness owns the disposable database configuration and canonical test.

It tests a baseline-to-candidate upgrade and a clean candidate replay in disposable PostgreSQL 17. SQL lint and the trusted pgTAP smoke test run on both. The current test verifies platform availability, not future app RLS or learner behavior. Add meaningful trusted schema checks as the app schema is introduced. Private app CI can provide supplementary tests, but a green candidate workflow alone is insufficient.

Only the apply step receives production writer credentials. It rechecks the private production head and CI, validates the local migration digest, compares remote version history to the reviewed baseline, links the fixed production project, performs the standard CLI dry run, applies with `db push --skip-vault`, then checks resulting history. Supabase CLI is pinned to `2.120.0`.

## Credential and activation prerequisites

The human bootstrap owner must verify these service settings and record the actual evidence in the reviewed policy. A receipt hash is an audit reference, not a replacement for GitHub's enforcement.

- `supabase-production` requires reviewer Bandar1011, user ID `210632822`, with self-review prohibited and administrator bypass disabled. Its selected deployment branch is exactly `main`.
- The requester GitHub App has public repository Actions write and Contents read only. It has no public Contents or Workflows write, administration, environment/secrets management, or deployment approval capability. A separate private app writer credential must not grant writes to this repository.
- A no-secret rehearsal under that actual App identity must wait for Bandar, reject agent approval, accept human approval, and demonstrate rejection prevents execution. Record the run ID and capability-denial evidence.
- Broad owner GitHub credentials and authenticated owner browser access must be removed from routine agent access before claiming independent human-only approval. This repository cannot enforce that local credential boundary.
- A human reviews the initial remote history and matching private baseline. Populate the baseline source SHA, migration count and SHA256 digest of the sorted filename/content-SHA256 manifest. An empty baseline is valid only when verified against the actual project. The null bootstrap policy is deliberately unusable.

Install these **environment secrets only after verification**, never repository secrets or local production writer files.

| Secret | Permission/owner |
| --- | --- |
| `SOURCE_READ_TOKEN` | Private app Contents read and Actions read, no app writes |
| `PRODUCTION_ACCESS_TOKEN` | Production-project-only scoped PAT with Database read for history and the documented Project Settings/API Keys/API Key Secrets reads needed by CLI linking |
| `PRODUCTION_DB_PASSWORD` | Production writer password, available only to the protected apply step |

The PAT scope does not constrain a separately usable database password. Never provide that password to local Codex. Production inspection uses a separate project-only Database Read credential in the app's local reader workflow.

`activation_evidence` records the verified requester login/user ID, rehearsal run ID, and SHA256 references for protection readback, capability-denial checks and removal of routine owner access. Keep underlying sensitive evidence private. Do not populate placeholder receipts or enable a writer path from a manually asserted readiness flag.

## Baseline and failure handling

The public baseline contains only a source SHA, manifest digest and migration count. SQL, filenames and detailed database output remain private. Manifest records are sorted `[filename, sha256(file bytes)]` arrays serialized as compact JSON, then SHA256 hashed. Historical files cannot change or disappear. New numeric migration versions must follow every deployed version.

After a successful deployment, a human-reviewed tooling change records the new verified baseline digest/count/source SHA before another deployment. If this update is omitted, subsequent requests fail closed against remote history. CLI pushes are sequential and are not an atomic rollback of the entire batch. A partial push also blocks subsequent attempts until a human reviews actual history and an appropriate reconciliation or forward fix. Do not edit deployed migration history to make a retry pass. Destructive changes need an explicit recovery and backup plan in the private review.

Remote history comparison assumes the reviewed baseline represents actual deployed SQL. Version numbers alone cannot retrospectively attest the bytes of an unmanaged deployment. Initial bootstrap and any manual/break-glass database change require reconciliation.

## Public log privacy

Only fixed statuses, commit revisions, manifest digests and migration counts are printed. Every private CLI subprocess combines stdout/stderr into an owner-only temporary file. API errors and Python exceptions produce only `BLOCKED`. There are no private artifact uploads. The protected runner is hosted and ephemeral. Cleanup removes the private workspace even after failure.

Do not add shell tracing, raw exception printing, database output replay, candidate script execution, or debug artifact uploads. Supabase errors can contain SQL and row details. Secret masking does not protect that private content.

## Verification

Run `python3 -m unittest discover -s tests -p 'test_*.py'`. Tests use synthetic fixtures and a network-denial guard. They cover immutable revisions, historical edits/deletions/order, malformed paths and symlinks, exact CI binding, missing activation/baseline, output containment and remote history validation.

Offline tests do not prove live approval gating, GitHub App permissions, private API access, CLI linking, hosted migration replay, or production deployment. Those remain activation checks. No production deployment has been performed by this setup.

Official action pins were checked against the upstream tag refs on 2026-10-13. [Checkout v4.2.2](https://github.com/actions/checkout/tree/11bd71901bbe5b1630ceea73d27597364c9af683) and [Supabase setup-cli v3.0.1](https://github.com/supabase/setup-cli/tree/45a513f8c64c0bc8e0e3dfe572b5c95be85f6359) are pinned by full commit. [Supabase PAT permissions](https://supabase.com/docs/guides/platform/personal-access-tokens) document the CLI linking scopes. [GitHub environment protection](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments) governs reviewer and secret release behavior.
