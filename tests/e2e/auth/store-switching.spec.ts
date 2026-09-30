import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
const tenantA = "10000000-0000-4000-8000-000000000001";
const tenantB = "10000000-0000-4000-8000-000000000002";
const storeB = "20000000-0000-4000-8000-000000000002";
async function login(page: Page, profile: string) {
  await page.goto("/");
  await page.getByRole("main").getByRole("link", { name: "로그인", exact: true }).click();
  await page.getByRole("button", { name: profile, exact: true }).click();
  await expect(page.getByRole("heading", { name: "내 매장", exact: true })).toBeVisible();
}
test.beforeEach(async ({ request }) => { await request.post("http://127.0.0.1:9100/__test/reset"); });
for (const failure of ["nonce", "signature", "audience", "issuer", "expired"]) {
  test(`rejects signed issuer response with invalid ${failure}`, async ({ page, context, request }) => {
    await request.post(`http://127.0.0.1:9100/__test/token-mode?value=${failure}`);
    await page.goto("/api/auth/login");
    await page.getByRole("button", { name: "single", exact: true }).click();
    await expect(page.getByRole("heading", { name: "요청을 완료할 수 없습니다" })).toBeVisible();
    expect((await context.cookies()).some(cookie => cookie.name === "__Host-wso-session" || cookie.name === "__Host-wso-flow")).toBe(false);
    await expect(page.getByRole("link", { name: "다시 로그인" })).toBeVisible();
  });
}
test("single store login uses secure opaque cookies and allows detail/back", async ({ page, context }) => {
  await login(page, "single");
  await expect(page.getByRole("link", { name: /매장 열기/ })).toHaveCount(1);
  const cookies = await context.cookies();
  expect(cookies.find(c => c.name === "__Host-wso-session")).toMatchObject({ secure: true, httpOnly: true, sameSite: "Lax", path: "/" });
  expect(cookies.find(c => c.name === "__Host-wso-csrf")).toMatchObject({ secure: true, httpOnly: false, sameSite: "Strict" });
  expect(cookies.find(c => c.name === "__Host-wso-flow")).toBeUndefined();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  await page.getByRole("link", { name: /강남점.*매장 열기/ }).click();
  await expect(page.getByRole("heading", { name: "강남점", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "내 매장", exact: true })).toBeVisible();
});
test("multiple stores switch tenants and browser back revalidates selection", async ({ page }) => {
  await login(page, "multi");
  await expect(page.getByRole("link", { name: /매장 열기/ })).toHaveCount(2);
  await page.getByLabel("조직 선택").selectOption(tenantB);
  await page.getByRole("button", { name: "조직 전환" }).click();
  await expect(page).toHaveURL(new RegExp(tenantB));
  await expect(page.getByRole("link", { name: /부산점/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /강남점/ })).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole("link", { name: /강남점/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /부산점/ })).toHaveCount(0);
});
test("staff cannot open unassigned store or foreign tenant URLs", async ({ page }) => {
  await login(page, "staff");
  await expect(page.getByRole("link", { name: /매장 열기/ })).toHaveCount(1);
  await page.goto(`/stores/${storeB}?tenant_id=${tenantA}`);
  await expect(page.getByRole("heading", { name: "매장을 찾을 수 없습니다" })).toBeVisible();
  await expect(page.getByText("홍대점")).toHaveCount(0);
  await page.goto(`/stores?tenant_id=${tenantB}`);
  await expect(page.getByRole("heading", { name: "매장을 찾을 수 없습니다" })).toBeVisible();
});
test("empty membership shows actionable empty state", async ({ page }) => {
  await login(page, "empty");
  await expect(page.getByRole("status")).toContainText("접근할 수 있는 매장이 없습니다");
  await expect(page.getByRole("link", { name: /매장 열기/ })).toHaveCount(0);
});
test("expired session requires sign in again", async ({ page, request }) => {
  await login(page, "single");
  await request.post("http://127.0.0.1:9100/__test/expire");
  await page.reload();
  await expect(page).toHaveURL(/expired=1/);
  await expect(page.getByRole("status")).toContainText("로그인이 만료되었습니다");
});
test("callback mismatched state consumes flow cookie and cannot be replayed", async ({ page, context }) => {
  await page.goto("/api/auth/login");
  const response = await context.request.get("/api/auth/callback?state=wrong&code=wrong");
  expect(response.status()).toBe(400);
  expect(await response.text()).not.toContain("private");
  expect((await context.cookies()).some(c => c.name === "__Host-wso-flow")).toBe(false);
  expect((await context.request.get("/api/auth/callback?state=wrong&code=wrong")).status()).toBe(400);
});
test("successful callback replay fails, GET logout preserves session and POST revokes", async ({ page, context }) => {
  let callback = "";
  page.on("request", request => { if (request.url().includes("/api/auth/callback?")) callback = request.url(); });
  await login(page, "multi");
  expect(callback).toContain("state=");
  expect((await context.request.get(callback)).status()).toBe(400);
  expect((await context.request.get("/api/auth/logout")).status()).toBe(405);
  await page.reload();
  await expect(page.getByRole("heading", { name: "내 매장", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/signed_out=1/);
  expect((await context.cookies()).some(c => c.name === "__Host-wso-session" || c.name === "__Host-wso-csrf")).toBe(false);
  await page.goBack();
  await expect(page).toHaveURL(/expired=1/);
});
test("service failure shows retry state without leaking internals", async ({ page, request }) => {
  await login(page, "single");
  await request.post("http://127.0.0.1:9100/__test/fail-stores");
  await page.reload();
  await expect(page.getByRole("heading", { name: "매장을 불러올 수 없습니다" })).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
});
test("reference layout works on desktop and mobile with keyboard navigation", async ({ page, request }) => {
  mkdirSync("auth-state/ui-review", { recursive: true });
  for (const [name, width, height] of [["desktop", 1440, 900], ["mobile", 390, 844]] as const) {
    await page.context().clearCookies();
    await request.post("http://127.0.0.1:9100/__test/reset");
    await page.setViewportSize({ width, height });
    await page.goto("/");
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "본문으로 이동" })).toBeFocused();
    await page.keyboard.press("Tab");
    await page.screenshot({ path: `auth-state/ui-review/login-${name}.png`, fullPage: true, caret: "initial", style: "nextjs-portal { display: none; }" });
    await login(page, "multi");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    if (name === "mobile") {
      await page.locator("summary").click();
      await expect(page.locator(".wso-mobile-menu").getByRole("link", { name: "내 매장", exact: true })).toBeVisible();
      await page.locator("summary").click();
    }
    await page.screenshot({ path: `auth-state/ui-review/stores-${name}.png`, fullPage: true, caret: "initial", style: "nextjs-portal { display: none; }" });
  }
  await page.goto("/api/auth/callback");
  await expect(page.getByRole("heading", { name: "요청을 완료할 수 없습니다" })).toBeVisible();
  await page.screenshot({ path: "auth-state/ui-review/auth-error-mobile.png", fullPage: true, caret: "initial", style: "nextjs-portal { display: none; }" });
});
