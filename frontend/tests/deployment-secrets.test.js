import test from "node:test";
import assert from "node:assert/strict";
import {
  secretInputError,
  checkedRequirements,
  continuationRequest,
} from "../src/services/deployment-secrets.js";

const job = {
  id: "job-123",
  repository: "https://github.com/team/demo.git",
  subdomain: "demo",
  appId: "app-123",
};

test("secret input accepts a single-line value within the engine byte limit", () => {
  assert.equal(secretInputError("sk-example"), "");
  assert.ok(secretInputError(""));
  assert.ok(secretInputError("line1\nline2"));
  assert.ok(secretInputError("line1\rline2"));
  assert.ok(secretInputError("a\0b"));
  assert.ok(secretInputError("密".repeat(5462)));
});

test("requirements must belong to the selected job and expose metadata only", () => {
  const data = {
    jobId: job.id,
    repository: job.repository,
    subdomain: job.subdomain,
    canGenerate: true,
    items: [{
      name: "MODEL_API_KEY", state: "missing", managed: false,
      uses: [{ service: "web", environmentVariable: "MODEL_API_KEY" }],
    }],
  };
  assert.deepEqual(checkedRequirements(job, data), data);
  assert.throws(() => checkedRequirements(job, { ...data, jobId: "other" }));
  assert.throws(() => checkedRequirements(job, { ...data, items: [data.items[0], data.items[0]] }));
  assert.throws(() => checkedRequirements(job, { ...data, items: [{ ...data.items[0], value: "raw-key" }] }));
});

test("continuation keeps the original app identity and stable retry key", () => {
  assert.deepEqual(continuationRequest(job), {
    body: { repository: job.repository, name: "demo", app_id: "app-123" },
    key: "configure-job-123",
  });
  assert.deepEqual(continuationRequest({ ...job, appId: null }).body, {
    repository: job.repository, name: "demo",
  });
});
