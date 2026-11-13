# Deployment secret preflight design

## User flow

The wizard has five stages: choose application, connect repository, configure runtime secrets, confirm project name, and review. After the repository is entered, the server fetches `main` through the engine's allowlisted Git transport, pins the commit, validates the root `awesome.yaml`, and returns only `app.subdomain`, the commit, and unique `secretRefs` names with their service/environment uses. `env` literals are not requested. A manifest with no references skips the secret stage and shows a brief no-configuration notice on the name stage. The name stage is prefilled from `app.subdomain`, which the engine already requires to match the requested domain.

For an existing app, the server checks deploy access and returns only each reference's configured/missing/unavailable state. Existing values are never returned or overwritten. A `MASTER_KEY` reference is platform managed and has no text field. If the manifest has no user-entered references, the wizard skips the secret stage and advances straight from repository to project name after a brief “无需配置密钥” status. New values remain in component memory until final confirmation; leaving the wizard clears them. The review displays names and status only.

## Submission and identity

The final request carries repository, selected app, requested name, inspected commit, idempotency key, and only missing user-entered values. The server re-fetches and validates `main`, rejects a changed commit, checks that the name matches `app.subdomain`, checks exact reference names, and validates the app's ownership. The server pins the job to that commit. On encrypted-vault installations, application creation, missing-value insertion, managed-key generation, and job enqueue share a single SQLite transaction while the worker lock is held. Plaintext is never persisted in jobs, logs, Redis, Feishu, browser storage, or Git. A failed transaction creates neither a job nor a partial secret. Legacy file-secret installations keep the existing post-failure recovery path until their vault is migrated; the preflight UI must state that limitation rather than claim it saved values.

An idempotent retry returns its original job without reusing plaintext. A changed branch requires a new preflight. The worker still validates and pins the source, manifest, identity, and runtime secrets; preflight does not replace the execution gate.

## Error states

The repository stage shows controlled errors for unreachable/disallowed/private repositories, missing or invalid `awesome.yaml`, and mismatched app identity. The secret stage handles loading, empty, configured, missing, unavailable, validation, and retry states. It never displays secret values after input has been cleared. The name stage shows a prefilled domain and availability feedback. Keyboard focus moves to the first error; secret inputs remain masked by default. The existing visual language, spacing, and controls are retained.

## Release

Tests cover source limits, manifest extraction, ownership, changed commits, absent and duplicate references, missing/managed/configured/unavailable secrets, atomic rollback, idempotency, and wizard states. Source is committed and pushed before any production rollout. Production checks compare the deployed build to the pushed revision and verify unchanged app/job data and integrations.
