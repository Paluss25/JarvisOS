import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { test } from "node:test";

import { extractHtmlText } from "../src/extract.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

async function fixture(name) {
  return readFile(join(__dirname, "fixtures", name), "utf8");
}

test("extracts the readable article as markdown and drops page chrome", async () => {
  const html = await fixture("article.html");

  const result = extractHtmlText(html, {
    source: "article.html",
    format: "markdown",
  });

  assert.equal(result.title, "GLM OCR Rollout Notes");
  assert.equal(result.byline, null);
  assert.match(result.content, /^# GLM OCR Rollout Notes/);
  assert.match(result.content, /dense scanned PDFs through GLM OCR/);
  assert.doesNotMatch(result.content, /Home Pricing Contact/);
  assert.doesNotMatch(result.content, /Copyright 2026/);
  assert.equal(result.readabilityUsed, true);
  assert.equal(result.source, "article.html");
});

test("falls back to full page conversion when Readability cannot find an article", async () => {
  const html = await fixture("plain-page.html");

  const result = extractHtmlText(html, {
    source: "plain-page.html",
    format: "text",
    fallback: "full-page",
  });

  assert.equal(result.title, "Status Page");
  assert.match(result.content, /Service Status/);
  assert.match(result.content, /All document pipelines are healthy/);
  assert.equal(result.readabilityUsed, false);
});
