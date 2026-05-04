import { Readability } from "@mozilla/readability";
import { JSDOM } from "jsdom";
import TurndownService from "turndown";

const DEFAULT_FALLBACK = "full-page";
const DEFAULT_MIN_READABLE_LENGTH = 120;

function normalizeFormat(format) {
  if (!format || format === "markdown" || format === "text") {
    return format || "markdown";
  }
  throw new Error(`Unsupported format: ${format}`);
}

function htmlToMarkdown(html) {
  const turndown = new TurndownService({
    headingStyle: "atx",
    codeBlockStyle: "fenced",
  });
  return turndown.turndown(html).trim();
}

function markdownToText(markdown) {
  return markdown
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function removePageChrome(document) {
  for (const selector of ["script", "style", "noscript", "nav", "footer"]) {
    for (const node of document.querySelectorAll(selector)) {
      node.remove();
    }
  }
}

function fallbackContent(document) {
  removePageChrome(document);
  const main = document.querySelector("main, article, section") || document.body;
  return main?.innerHTML || "";
}

function firstHeadingFromHtml(html) {
  const fragment = JSDOM.fragment(html);
  return fragment.querySelector("h1, h2, h3")?.textContent?.trim() || null;
}

function normalizeFirstHeading(html) {
  const fragment = JSDOM.fragment(html);
  const heading = fragment.querySelector("h1, h2, h3");
  if (!heading || heading.tagName.toLowerCase() === "h1") {
    return html;
  }
  const h1 = fragment.ownerDocument.createElement("h1");
  h1.innerHTML = heading.innerHTML;
  heading.replaceWith(h1);
  const container = fragment.ownerDocument.createElement("div");
  container.append(fragment);
  return container.innerHTML;
}

export function extractHtmlText(html, options = {}) {
  const format = normalizeFormat(options.format);
  const fallback = options.fallback || DEFAULT_FALLBACK;
  const minReadableLength = options.minReadableLength ?? DEFAULT_MIN_READABLE_LENGTH;
  const dom = new JSDOM(html, { url: options.url || "https://example.invalid/" });
  const reader = new Readability(dom.window.document.cloneNode(true));
  const article = reader.parse();

  let title = article?.title || dom.window.document.title || null;
  let byline = article?.byline || null;
  let contentHtml = article?.content || "";
  let readabilityUsed = Boolean(
    article?.content &&
    article.textContent?.trim() &&
    (article.length ?? article.textContent.length) >= minReadableLength
  );

  if (!readabilityUsed) {
    if (fallback === "none") {
      contentHtml = "";
    } else if (fallback === "full-page") {
      contentHtml = fallbackContent(dom.window.document);
    } else {
      throw new Error(`Unsupported fallback: ${fallback}`);
    }
  }

  if (readabilityUsed) {
    title = firstHeadingFromHtml(contentHtml) || title;
    contentHtml = normalizeFirstHeading(contentHtml);
  }

  let content = htmlToMarkdown(contentHtml);
  if (format === "text") {
    content = markdownToText(content);
  }

  return {
    source: options.source || null,
    title,
    byline,
    content,
    readabilityUsed,
  };
}
