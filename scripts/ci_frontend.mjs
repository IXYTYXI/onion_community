import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const frontendRoot = resolve(dirname(scriptPath), "../frontend");
const ignored = new Set(["dist", "node_modules"]);

export function inputDigest(root, ciScript) {
  const hash = createHash("sha256");
  hash.update("ows-frontend-ci-v1\0");
  hash.update(readFileSync(ciScript));
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (directory === root && ignored.has(entry.name)) continue;
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(path);
      } else if (entry.isFile()) {
        hash.update(relative(root, path));
        hash.update("\0");
        hash.update(readFileSync(path));
        hash.update("\0");
      } else {
        throw new Error(`unsupported frontend input: ${path}`);
      }
    }
  }
  visit(root);
  return hash.digest("hex");
}

export function cachedBuildMatches(root, digest) {
  const dist = join(root, "dist");
  try {
    if (readFileSync(join(dist, ".ci-input-sha256"), "utf8").trim() !== digest) return false;
    const pages = readdirSync(root).filter((name) => name.endsWith(".html"));
    if (pages.length === 0 || pages.some((page) => !existsSync(join(dist, page)))) return false;
    const manifest = JSON.parse(readFileSync(join(dist, ".vite/manifest.json"), "utf8"));
    if (Object.keys(manifest).length === 0) return false;
    for (const entry of Object.values(manifest)) {
      for (const asset of [entry.file, ...(entry.css ?? []), ...(entry.assets ?? [])]) {
        if (!asset || asset.startsWith("/") || asset.includes("..") || !existsSync(join(dist, asset))) return false;
      }
    }
    return true;
  } catch {
    return false;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  const digest = inputDigest(frontendRoot, scriptPath);
  if (cachedBuildMatches(frontendRoot, digest)) {
    console.log(`frontend-cache-hit: ${digest}`);
  } else {
    console.log(`frontend-cache-miss: ${digest}; testing and building`);
    rmSync(join(frontendRoot, "dist"), { recursive: true, force: true });
    for (const args of [["ci", "--prefer-offline"], ["test"], ["run", "build"]]) {
      execFileSync("npm", args, { cwd: frontendRoot, stdio: "inherit" });
    }
    writeFileSync(join(frontendRoot, "dist/.ci-input-sha256"), `${digest}\n`);
  }
}
