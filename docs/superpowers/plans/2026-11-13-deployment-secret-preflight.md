# Deployment Secret Preflight Implementation Plan

> **For agentic workers:** Implement in this session with test-first checkpoints. No subagent is required.

**Goal:** Show YAML-declared runtime secret fields before the project-name stage and safely create a first deployment without an avoidable missing-secret failure.

**Architecture:** A bounded, authenticated Git preflight reads and validates the root manifest from `main`. The final submit rechecks its commit. A transaction-scoped hook inserts only missing encrypted vault values and the deployment job together. The Vue wizard holds entered values in memory, displays status rather than values, and binds its final request to the inspected commit.

**Tech Stack:** FastAPI, Python deploy engine, SQLite encrypted vault, Vue 3, Node test runner, pytest.

---

### Task 1: Bounded manifest inspection

**Files:** `packages/deploy-engine/src/awesome_deploy/source.py`, `packages/deploy-engine/tests/test_source.py`.

- [ ] Write a failing test for public `main` inspection that returns a validated manifest and commit without exporting an application tree.
- [ ] Add failing cases for missing/oversized/invalid YAML, forbidden Git host, and hidden Git output.
- [ ] Implement inspection using the existing bounded Git runner and `load_manifest`, with a private temporary bare repository and no shell or redirect.
- [ ] Run the focused source tests.

### Task 2: Preflight and atomic submission

**Files:** `app/api/deployment.py`, `app/deployment/service.py`, `app/schemas/deployment.py`, `packages/deploy-engine/src/awesome_deploy/store.py`, `tests/test_deployment.py`.

- [ ] Write failing API/service tests: authenticated preflight reports unique references, subdomain, commit, owner-scoped existing states, and no values; changed commit is rejected.
- [ ] Write failing store tests: app, encrypted missing secrets, managed `MASTER_KEY`, and queued job commit together; errors roll back all new rows; retries do not rotate values.
- [ ] Add a no-op transaction hook in engine `Store.enqueue`, invoked after app identity/vault registration and before job insert, only for new requests.
- [ ] Implement preflight using source inspection and existing authorization; implement encrypted-vault submission through the hook under the worker lock. Preserve legacy job submission and post-failure entry.
- [ ] Run focused API, engine, and vault tests.

### Task 3: Five-stage wizard

**Files:** `frontend/src/pages/Deploy.vue`, `frontend/src/composables/useDeployment.js`, `frontend/src/services/deployment-secrets.js`, `frontend/tests/deployment.test.js`.

- [ ] Write failing state tests for repository preflight, 5-stage navigation, no-reference state, masked missing inputs, stale-response handling, matching name, and final payload without browser storage.
- [ ] Add the in-memory secret stage and explicit loading/empty/configured/missing/unavailable/error states; keep existing visual system and accessible labels/focus.
- [ ] Bind review/submit to inspected commit, clear values after success or unmount, and warn before discarding typed values.
- [ ] Run frontend tests and production build.

### Task 4: Review and release

**Files:** `docs/DEPLOYMENT.md`, `README.md`.

- [ ] Update the documented flow and encrypted-vault requirement.
- [ ] Fetch current Web Interface Guidelines, review affected UI states, and operate the running desktop wizard including empty/loading/error/filled/long-text/scroll states without ego.
- [ ] Verify focused tests, diff, no secret literals, and manifest build; commit and push before production deployment.
- [ ] Stage and atomically install the pushed revision; check public health, source/build hash, services, read-only database integrity/counts, and rollback availability.
