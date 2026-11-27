import test from "node:test";
import assert from "node:assert/strict";
import {
  projectNameError,
  repositoryError,
  useDeployment,
} from "../src/composables/useDeployment.js";
import { checkedPreflight } from "../src/services/deployment-secrets.js";

test("preflight metadata rejects a response containing secret values", () => {
  assert.throws(() => checkedPreflight({
    repository: "https://github.com/team/repo.git", commit: "a".repeat(40),
    subdomain: "demo", canPreconfigure: true,
    items: [{ name: "API_KEY", uses: [], state: "missing", managed: false, value: "must-not-return" }],
  }), /不完整/);
});

test("deployment names enforce domain rules without silently correcting input", () => {
  for (const value of ["a", "0", "demo", "abc-123", "a--b", "1234567"])
    assert.equal(projectNameError(value), "", value);
  for (const value of [
    "",
    "abcdefgh",
    "-demo",
    "demo-",
    "Demo",
    "中文",
    "a b",
    " demo",
    "demo ",
    "demo\n",
    "demo\r",
    "a_b",
    "a.b",
  ])
    assert.ok(projectNameError(value), JSON.stringify(value));
});
test("repository syntax accepts GitHub and nested self-hosted GitLab repositories", () => {
  for (const value of [
    "https://github.com/team/project.git",
    "https://gitlab.com/team/group/project",
    "https://gitlab.example.org/team/repo",
    " https://github.com/team/repo ",
  ])
    assert.equal(repositoryError(value), "", value);
  for (const value of [
    "",
    "javascript:alert(1)",
    "https://github.com/team",
    "https://github.com/team/project/tree/main",
    "https://gitlab.com/team/project/-/tree/main",
    "https://token@github.com/team/repo",
    "https://github.com/team/repo?token=secret",
    "not a url",
  ])
    assert.ok(repositoryError(value), value);
});
test("wizard inspects the repository and skips secrets when YAML declares none", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  auth.request = async (path) => {
    assert.equal(path, "/api/v1/deployment/preflight");
    return { repository: "https://github.com/team/repo.git", commit: "a".repeat(40),
      subdomain: "demo", canPreconfigure: true, items: [] };
  };
  try {
    const w = useDeployment();
    w.next();
    w.form.repository = "https://github.com/team/repo";
    await w.next();
    assert.equal(w.step.value, 3);
    assert.equal(w.form.name, "demo");
    assert.deepEqual(w.preflight.value.items, []);
  } finally {
    auth.request = previous;
  }
});

test("wizard blocks missing secrets before the project-name stage", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  auth.request = async () => ({ repository: "https://github.com/team/repo.git",
    commit: "a".repeat(40), subdomain: "demo", canPreconfigure: true,
    items: [{ name: "API_KEY", uses: [{ service: "web", environmentVariable: "MODEL_KEY" }],
      state: "missing", managed: false }] });
  try {
    const w = useDeployment();
    w.next();
    w.form.repository = "https://github.com/team/repo";
    await w.next();
    assert.equal(w.step.value, 2);
    w.next();
    assert.equal(w.step.value, 2);
    w.secretValues.API_KEY = "fixture-value";
    w.next();
    assert.equal(w.step.value, 3);
  } finally {
    auth.request = previous;
  }
});

test("wizard cannot skip steps, blocks invalid fields and retains input on backtracking", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  auth.request = async () => ({ repository: "https://github.com/team/repo.git",
    commit: "a".repeat(40), subdomain: "demo", canPreconfigure: true, items: [] });
  try {
  const w = useDeployment();
  assert.equal(w.form.application, "create");
  w.back(4);
  w.submit();
  assert.equal(w.step.value, 0);
  assert.equal(w.notice.value, "");
  w.next();
  assert.equal(w.step.value, 1);
  w.next();
  assert.equal(w.step.value, 1);
  assert.equal(w.touched[1], true);
  w.form.repository = "https://github.com/team/repo";
  await w.next();
  assert.equal(w.step.value, 3);
  w.form.name = "Bad";
  w.next();
  assert.equal(w.step.value, 3);
  w.form.name = "demo";
  w.next();
  assert.equal(w.step.value, 4);
  w.back(0);
  assert.equal(w.step.value, 0);
  assert.equal(w.form.name, "demo");
  assert.equal(w.form.repository, "https://github.com/team/repo");
  w.back(3);
  assert.equal(w.step.value, 0);
  w.next();
  await w.next();
  w.next();
  w.submit();
  assert.match(w.notice.value, /暂未发起部署/);
  } finally {
    auth.request = previous;
  }
});
test("final preview revalidates all fields and never claims a real deployment", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  auth.request = async () => ({ repository: "https://github.com/team/repo.git",
    commit: "a".repeat(40), subdomain: "demo", canPreconfigure: true, items: [] });
  try {
  const w = useDeployment();
  w.form.repository = "https://github.com/team/repo";
  w.form.name = "demo";
  w.next();
  await w.next();
  w.next();
  w.form.repository = "";
  await w.submit();
  assert.equal(w.step.value, 1);
  assert.equal(w.notice.value, "");
  } finally {
    auth.request = previous;
  }
});

test("deployment submission uses API and reuses idempotency key after an uncertain response", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  const calls = [];
  auth.request = async (path, options) => {
    if (path === "/api/v1/deployment/preflight")
      return { repository: "https://github.com/team/repo.git", commit: "a".repeat(40),
        subdomain: "demo", canPreconfigure: true, items: [] };
    calls.push({ path, options });
    throw new Error("网络异常");
  };
  try {
    const w = useDeployment();
    w.options.value.executionEnabled = true;
    w.form.repository = "https://github.com/team/repo";
    w.form.name = "demo";
    w.next();
    await w.next();
    w.next();
    await w.submit();
    await w.submit();
    assert.equal(calls.length, 2);
    assert.equal(calls[0].path, "/api/v1/deployment/jobs");
    assert.equal(
      calls[0].options.headers["Idempotency-Key"],
      calls[1].options.headers["Idempotency-Key"],
    );
    assert.equal(w.busy.value, false);
    assert.equal(w.job.value, null);
  } finally {
    auth.request = previous;
  }
});

test("final deployment request sends only declared missing values and inspected commit", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  let request;
  auth.request = async (path, options) => {
    if (path === "/api/v1/deployment/preflight")
      return { repository: "https://github.com/team/repo.git", commit: "a".repeat(40),
        subdomain: "demo", canPreconfigure: true,
        items: [{ name: "API_KEY", uses: [{ service: "web", environmentVariable: "MODEL_KEY" }],
          state: "missing", managed: false },
        { name: "DATA_MASTER", uses: [{ service: "web", environmentVariable: "MASTER_KEY" }],
          state: "missing", managed: true }] };
    request = { path, options };
    throw new Error("synthetic connection loss");
  };
  try {
    const w = useDeployment();
    w.options.value.executionEnabled = true;
    w.next();
    w.form.repository = "https://github.com/team/repo";
    await w.next();
    w.secretValues.API_KEY = "fixture-only-value";
    w.next();
    w.next();
    await w.submit();
    assert.equal(request.path, "/api/v1/deployment/jobs");
    const body = JSON.parse(request.options.body);
    assert.equal(body.commit, "a".repeat(40));
    assert.deepEqual(body.values, { API_KEY: "fixture-only-value" });
    assert.equal(JSON.stringify(body).includes("DATA_MASTER"), false);
  } finally {
    auth.request = previous;
  }
});

test("selecting a new task ignores late results from the previous task", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  const pending = {};
  auth.request = (path, options) =>
    path.endsWith("/jobs")
      ? Promise.resolve([])
      : new Promise((resolve) => {
          pending[path.split("/").at(-1)] = { resolve, signal: options.signal };
        });
  try {
    const w = useDeployment();
    const first = w.viewJob({ id: "first", terminal: true });
    const second = w.viewJob({ id: "second", terminal: true });
    assert.equal(pending.first.signal.aborted, true);
    pending.second.resolve({ id: "second", terminal: true });
    await second;
    pending.first.resolve({ id: "first", terminal: true });
    await first;
    assert.equal(w.job.value.id, "second");
  } finally {
    auth.request = previous;
  }
});

test("a continued deployment appears in history before its first poll completes", async () => {
  const { auth } = await import("../src/services/auth.js");
  const previous = auth.request;
  let resolvePoll;
  auth.request = (path) => path.endsWith("/jobs/continued")
    ? new Promise((resolve) => { resolvePoll = resolve; })
    : Promise.resolve([{ id: "continued", terminal: true }, { id: "failed", terminal: true }]);
  try {
    const w = useDeployment();
    w.history.value = [{ id: "failed", terminal: true }];
    const pending = w.viewJob({ id: "continued", terminal: false });
    assert.equal(w.history.value[0].id, "continued");
    resolvePoll({ id: "continued", terminal: true });
    await pending;
  } finally {
    auth.request = previous;
  }
});

test("existing application options retain the latest task", () => {
  const w = useDeployment();
  w.history.value = [
    { id: "new", appId: "a", subdomain: "demo" },
    { id: "old", appId: "a", subdomain: "demo" },
  ];
  assert.equal(w.applications.value[0].id, "new");
});

test("applications deduplicate subdomains, hide offline apps, and isolate personal scope by default", () => {
  const w = useDeployment();
  w.history.value = [
    { id: "other-fail", appId: "app-other", subdomain: "vibevot", mine: false, appOnline: false, appUpdatable: true, everSucceeded: false, updatedAt: 500 },
    { id: "upic-live", appId: "app-upic-2", subdomain: "upic", mine: true, appOnline: true, appUpdatable: true, everSucceeded: true, updatedAt: 400 },
    { id: "upic-old-offline", appId: "app-upic-1", subdomain: "upic", mine: true, appOnline: false, appUpdatable: false, everSucceeded: true, updatedAt: 300 },
    { id: "test-dup-1", appId: "app-test-2", subdomain: "test", mine: true, appOnline: true, appUpdatable: true, everSucceeded: true, updatedAt: 200 },
    { id: "test-dup-0", appId: "app-test-1", subdomain: "test", mine: true, appOnline: false, appUpdatable: true, everSucceeded: false, updatedAt: 250 },
  ];
  assert.equal(w.hasOtherUsersRecords.value, true);
  assert.deepEqual(
    w.applications.value.map((item) => [item.appId, item.subdomain]),
    [
      ["app-upic-2", "upic"],
      ["app-test-2", "test"],
    ],
  );
  w.scopeMode.value = "all";
  assert.deepEqual(
    w.applications.value.map((item) => item.subdomain),
    ["upic", "test", "vibevot"],
  );
});
