# JusTalk deployment repository

This is a public deployment-only repository. Never copy app source, SQL migrations, tokens, private logs, or production data into tracked files, public Actions logs or public artifacts. Keep app source in Bandar1011/English-Learning-App.

Use one main branch for trusted deployment tooling. The normal deployment requester must have no Contents/Workflows write, administration, environment/secret management or deployment-approval permissions here. Human owner approval is required before a protected production job receives credentials. Bind both harness and private source commit SHAs; never follow mutable source HEAD after approval.

Use hosted ephemeral runners, pinned official actions and Supabase CLI, capture all private subprocess output, and publish only fixed status and nonconfidential revision/digest/count metadata. Never use pull_request_target with private credentials or execute an untrusted source helper under production credentials.

Do not store production writer credentials locally. Keep them in the protected production environment only after actual protection and no-secret rehearsal verification. Configuration alone is not a working deployment. Keep app promotion order development -> staging -> production.

Only Fal and customized project pstack plugins are approved; use CLI/direct APIs otherwise. Commits and normal pushes are authorized after validation. No production deployment or promotion without a specific user approval.
