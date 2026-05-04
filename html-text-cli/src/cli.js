#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises";
import process from "node:process";

import { extractHtmlText } from "./extract.js";

function usage() {
  return `Usage:
  html-text extract <file|url|-> [--format markdown|text|json] [--output path] [--fallback full-page|none]

Examples:
  html-text extract page.html
  html-text extract https://example.com/article --format json
  cat page.html | html-text extract - --format text
`;
}

function parseArgs(argv) {
  const [command, input, ...rest] = argv;
  if (command !== "extract" || !input) {
    throw new Error(usage());
  }

  const options = {
    command,
    input,
    format: "markdown",
    fallback: "full-page",
    output: null,
  };

  for (let i = 0; i < rest.length; i += 1) {
    const arg = rest[i];
    if (arg === "--format") {
      options.format = rest[++i];
    } else if (arg === "--output" || arg === "-o") {
      options.output = rest[++i];
    } else if (arg === "--fallback") {
      options.fallback = rest[++i];
    } else if (arg === "--help" || arg === "-h") {
      throw new Error(usage());
    } else {
      throw new Error(`Unknown argument: ${arg}\n\n${usage()}`);
    }
  }

  return options;
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function readInput(input) {
  if (input === "-") {
    return { html: await readStdin(), source: "stdin", url: null };
  }

  if (/^https?:\/\//i.test(input)) {
    const response = await fetch(input);
    if (!response.ok) {
      throw new Error(`Fetch failed: ${response.status} ${response.statusText}`);
    }
    return { html: await response.text(), source: input, url: input };
  }

  return { html: await readFile(input, "utf8"), source: input, url: null };
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const { html, source, url } = await readInput(options.input);
  const result = extractHtmlText(html, {
    source,
    url,
    format: options.format === "json" ? "markdown" : options.format,
    fallback: options.fallback,
  });

  const output = options.format === "json"
    ? `${JSON.stringify(result, null, 2)}\n`
    : `${result.content}\n`;

  if (options.output) {
    await writeFile(options.output, output, "utf8");
  } else {
    process.stdout.write(output);
  }
}

main().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
});
