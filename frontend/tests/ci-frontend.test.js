import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { cachedBuildMatches, inputDigest } from "../../scripts/ci_frontend.mjs";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "ows-ci-frontend-"));
  mkdirSync(join(root, "src"));
  writeFileSync(join(root, "src/app.js"), "version 1");
  const script = join(root, "ci.mjs");
  writeFileSync(script, "ci version 1");
  return { root, script };
}

test("frontend fingerprint changes with source and CI logic", () => {
  const { root, script } = fixture();
  const initial = inputDigest(root, script);
  writeFileSync(join(root, "src/app.js"), "version 2");
  assert.notEqual(inputDigest(root, script), initial);
  writeFileSync(join(root, "src/app.js"), "version 1");
  writeFileSync(script, "ci version 2");
  assert.notEqual(inputDigest(root, script), initial);
});

test("generated files do not change the frontend fingerprint", () => {
  const { root, script } = fixture();
  const initial = inputDigest(root, script);
  mkdirSync(join(root, "dist"));
  writeFileSync(join(root, "dist/index.html"), "old build");
  mkdirSync(join(root, "node_modules"));
  writeFileSync(join(root, "node_modules/tool.js"), "installed package");
  assert.equal(inputDigest(root, script), initial);
});

test("cached build requires matching fingerprint and complete assets", () => {
  const { root, script } = fixture();
  const digest = inputDigest(root, script);
  const dist = join(root, "dist");
  mkdirSync(join(dist, ".vite"), { recursive: true });
  mkdirSync(join(dist, "assets"));
  writeFileSync(join(root, "index.html"), "source page");
  writeFileSync(join(dist, "index.html"), "built page");
  writeFileSync(join(dist, ".vite/manifest.json"), JSON.stringify({
    "index.html": { file: "assets/main.js", css: ["assets/main.css"] },
  }));
  writeFileSync(join(dist, "assets/main.js"), "js");
  writeFileSync(join(dist, "assets/main.css"), "css");
  writeFileSync(join(dist, ".ci-input-sha256"), digest);
  assert.equal(cachedBuildMatches(root, digest), true);
  assert.equal(cachedBuildMatches(root, "different"), false);
  rmSync(join(dist, "assets/main.js"));
  assert.equal(cachedBuildMatches(root, digest), false);
  writeFileSync(join(dist, ".vite/manifest.json"), "not json");
  assert.equal(cachedBuildMatches(root, digest), false);
});
