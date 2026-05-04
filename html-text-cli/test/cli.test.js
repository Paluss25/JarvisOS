import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { test } from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const cliPath = join(__dirname, "..", "src", "cli.js");
const articlePath = join(__dirname, "fixtures", "article.html");

function runCli(args, stdin = null) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [cliPath, ...args], {
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    if (stdin !== null) {
      child.stdin.end(stdin);
    } else {
      child.stdin.end();
    }
  });
}

test("prints markdown content for a file input", async () => {
  const result = await runCli(["extract", articlePath]);

  assert.equal(result.code, 0);
  assert.match(result.stdout, /^# GLM OCR Rollout Notes/);
  assert.match(result.stdout, /Marker remains a fallback/);
  assert.equal(result.stderr, "");
});

test("prints JSON metadata when requested", async () => {
  const result = await runCli(["extract", articlePath, "--format", "json"]);

  assert.equal(result.code, 0);
  const parsed = JSON.parse(result.stdout);
  assert.equal(parsed.title, "GLM OCR Rollout Notes");
  assert.equal(parsed.source, articlePath);
  assert.equal(parsed.readabilityUsed, true);
  assert.match(parsed.content, /dense scanned PDFs through GLM OCR/);
});
