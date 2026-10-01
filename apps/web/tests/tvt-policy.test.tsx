// @vitest-environment jsdom
import React from "react";
import { renderToString } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const web = existsSync(resolve("apps/web/package.json")) ? resolve("apps/web") : process.cwd();
const sourcePath = resolve(web, "src/features/tvt/policies/source.ts");
const readerPath = resolve(web, "src/features/tvt/policies/PolicyReader.tsx");
const pagePath = resolve(web, "src/app/tvt/policies/[locale]/[kind]/page.tsx");
const sourceModule = "../src/features/tvt/policies/source";
const readerModule = "../src/features/tvt/policies/PolicyReader";
const pageModule = "../src/app/tvt/policies/[locale]/[kind]/page";

it("ships a usable public server reader with original English and Chinese text", async () => {
  expect(existsSync(sourcePath), "safe bundled source must exist").toBe(true);
  expect(existsSync(readerPath), "public reader must exist").toBe(true);
  const { getPolicy } = await import(sourceModule);
  const { PolicyReader } = await import(readerModule);
  for (const [locale, kind, text] of [
    ["en", "terms", "Release/Effective Date: July 28, 2021"],
    ["en", "privacy", "Issuance/Effective Date: March 26, 2026"],
    ["zh-Hans", "terms", "服务协议"],
    ["zh-Hans", "privacy", "发布/生效日期：2026年3月26日"],
  ]) {
    const document = getPolicy(locale, kind)!;
    const html = renderToString(<PolicyReader document={document} />);
    expect(html).toContain("SuperLivePlus");
    expect(html).toContain(text);
    expect(html).toContain(`lang="${locale}"`);
    expect(html).not.toMatch(/<script|<iframe|<img|onclick=|common\.js|language\.js/);
    expect(html).not.toContain("tenant_id");
  }
});

it("allowlists exactly four public routes and sends unknown parameters to notFound", async () => {
  expect(existsSync(pagePath), "public route must exist").toBe(true);
  const page = await import(pageModule);
  expect(page.generateStaticParams()).toEqual([
    { locale: "en", kind: "terms" }, { locale: "en", kind: "privacy" },
    { locale: "zh-Hans", kind: "terms" }, { locale: "zh-Hans", kind: "privacy" },
  ]);
  const html = renderToString(await page.default({ params: Promise.resolve({ locale: "en", kind: "privacy" }) }));
  expect(html).toContain("<table");
  expect(html).toContain("<ol");
  for (const params of [{ locale: "ko", kind: "terms" }, { locale: "en", kind: "__proto__" }, { locale: "../en", kind: "privacy" }]) {
    let failure: unknown;
    try { await page.default({ params: Promise.resolve(params) }); } catch (error) { failure = error; }
    expect(failure instanceof Error ? failure.message : undefined).toMatch(/NEXT_HTTP_ERROR_FALLBACK;404/);
  }
});

it("server renders escaped text without touching browser, login, fetch or asset loading", async () => {
  const { getPolicy } = await import(sourceModule);
  const { PolicyReader } = await import(readerModule);
  vi.stubGlobal("window", undefined);
  vi.stubGlobal("fetch", () => { throw new Error("policy reader must not fetch"); });
  try {
    const original = getPolicy("en", "privacy")!;
    const html = renderToString(<PolicyReader document={{ ...original, blocks: [{ type: "paragraph", text: '<img src="https://evil.test/tracker" onerror="attack()">' }] }} />);
    expect(html).toContain("&lt;img");
    expect(html).not.toMatch(/<img|<script|<iframe/);
    expect(html).not.toContain('href="https://evil.test');
    expect(html).not.toContain("/api/auth");
  } finally { vi.unstubAllGlobals(); }
});
