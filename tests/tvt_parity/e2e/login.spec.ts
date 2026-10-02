import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { readFile, rename, writeFile } from "node:fs/promises";

// This suite runs only against the separately owned real PG → API → RPC →
// synthetic HTTPS upstream fixture. It never replaces Next/API responses.
// Account credentials/cookies are read from a private ephemeral state file;
// traces/screenshots/video must be off in the fixture config.
type FixtureState = {
  baseURL: string; tenantId: string; cookies: Parameters<BrowserContext["addCookies"]>[0];
  csrfToken: string; expiresAt: string; proofKind: "actual-pg-rpc-https";
  account: { email: string; phone?: string; password: string; imageCode: string; secondCode?: string };
  expectedProfile: { userName: string | null; nickname: string; accountType: number };
  controlFile?: string; sequence?: number;
};
const stateFile = process.env.WSO_TVT_ACCOUNT_BROWSER_STATE_FILE;
async function readState(): Promise<FixtureState> {
  const state = JSON.parse(await readFile(stateFile!, "utf8")) as FixtureState;
  if (state.proofKind !== "actual-pg-rpc-https" || new URL(state.baseURL).protocol !== "https:" || !/^[0-9a-f-]{36}$/i.test(state.tenantId) || !Array.isArray(state.cookies) || !Number.isFinite(Date.parse(state.expiresAt)) || Date.parse(state.expiresAt) <= Date.now()) throw new Error("Real account browser fixture is unavailable");
  return state;
}
async function freshState() {
  let state = await readState();
  if (state.controlFile && Number.isSafeInteger(state.sequence)) {
    const sequence = state.sequence! + 1;
    const temporary = `${state.controlFile}.request`;
    await writeFile(temporary, JSON.stringify({ op: "session", sequence }), { encoding: "utf8", mode: 0o600 }); await rename(temporary, state.controlFile);
    await expect.poll(async () => { state = await readState(); return state.sequence; }, { timeout: 15000, message: "Fresh real web session was not issued" }).toBe(sequence);
  }
  return state;
}
function detail(page: Page, label: string) { return page.locator("dl > div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${label}$`) }) }).locator("dd"); }
test("real account UI consumes challenges, logs in, refreshes USER generation and retains WSO after TVT logout", async ({ page, context, browser }, testInfo) => {
  test.skip(!stateFile, "Pending separate real PG/API/RPC/HTTPS browser fixture; component tests do not establish browser acceptance.");
  const state = await freshState(); await context.addCookies(state.cookies);
  const loginURL = `${state.baseURL}/api/tvt/identities/login?tenant_id=${state.tenantId}`;
  const origin = new URL(state.baseURL).origin;
  const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
  try {
    const signedOut = await anonymous.request.post(loginURL, { data: "{", headers: { Origin: origin, "Content-Type": "application/json" } });
    expect(signedOut.status()).toBe(401); expect((await signedOut.json()).error.code).toBe("authentication_required");
  } finally { await anonymous.close(); }
  const noCsrf = await context.request.post(loginURL, { data: {}, headers: { Origin: origin } });
  expect(noCsrf.status()).toBe(403); expect((await noCsrf.json()).error.code).toBe("csrf_rejected");
  const invalid = await context.request.post(loginURL, { data: { account: "PRIVATE_BROWSER_SENTINEL", secret: "PRIVATE_BROWSER_SENTINEL" }, headers: { Origin: origin, "X-CSRF-Token": state.csrfToken } });
  expect(invalid.status()).toBe(422); const invalidPublic = await invalid.json(); expect(invalidPublic.error.code).toBe("validation_error"); expect(JSON.stringify(invalidPublic).includes("PRIVATE_BROWSER_SENTINEL")).toBe(false);
  const methods: { path: string; method: string }[] = [];
  let refreshBody: { kind?: string; expected_generation?: number; reason?: string } | undefined;
  page.on("request", request => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/tvt/") || path === "/api/auth/logout") {
      methods.push({ path, method: request.method() });
      if (path.endsWith("/refresh")) refreshBody = request.postDataJSON();
    }
  });
  await page.goto(`${state.baseURL}/tvt/account?tenant_id=${encodeURIComponent(state.tenantId)}`);
  const consent = page.getByRole("button", { name: "동의", exact: true });
  await expect.poll(async () => (await consent.isVisible()) || (await page.getByLabel("비밀번호", { exact: true }).isVisible()), { message: "Authoritative startup should render consent or account form" }).toBe(true);
  if (await consent.isVisible()) await consent.click();
  await expect(page.getByLabel("비밀번호", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "계정", exact: true })).toHaveAttribute("href", `/tvt/account?tenant_id=${state.tenantId}`);
  const imageRequest = page.getByRole("button", { name: "이미지 확인 요청", exact: true });
  await imageRequest.focus(); await expect(imageRequest).toBeFocused(); await page.keyboard.press("Enter");
  await expect(page.getByAltText("로그인 확인 이미지")).toBeVisible();
  await expect.poll(() => page.getByAltText("로그인 확인 이미지").evaluate(image => (image as HTMLImageElement).naturalWidth), { message: "Owned challenge image should decode" }).toBeGreaterThan(0);
  await page.getByLabel("이미지 확인 코드", { exact: true }).fill(state.account.imageCode);
  await page.getByRole("button", { name: "이미지 코드 확인", exact: true }).click();
  await expect(page.getByText("이미지 코드를 확인했습니다. 로그인하려면 확인 이미지를 새로 요청하세요.", { exact: true })).toBeVisible();
  await expect(page.getByAltText("로그인 확인 이미지")).toHaveCount(0);
  await imageRequest.click(); await expect(page.getByAltText("로그인 확인 이미지")).toBeVisible();
  await page.getByLabel("이메일", { exact: true }).fill(state.account.email);
  await page.getByLabel("비밀번호", { exact: true }).fill(state.account.password);
  await page.getByLabel("이미지 확인 코드", { exact: true }).fill(state.account.imageCode);
  if (state.account.secondCode) await page.getByLabel("추가 확인 코드", { exact: true }).fill(state.account.secondCode);
  await page.getByRole("button", { name: "TVT 로그인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "현재 TVT 계정", exact: true })).toBeVisible();
  await expect(detail(page, "계정 상태")).toHaveText("READY");
  await expect(detail(page, "계정 유형")).toHaveText(String(state.expectedProfile.accountType));
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("추가 확인 코드", { exact: true })).toHaveValue("");
  await expect(page.getByAltText("로그인 확인 이미지")).toHaveCount(0);
  const generation = Number(await detail(page, "세션 버전").textContent()); expect(Number.isSafeInteger(generation) && generation >= 1).toBe(true);
  const identityId = await detail(page, "계정 ID").textContent(); expect(/^[0-9a-f-]{36}$/i.test(identityId ?? "")).toBe(true);
  const refreshed = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/refresh") && response.request().method() === "POST");
  await page.getByRole("button", { name: "TVT 세션 갱신", exact: true }).click(); expect((await refreshed).status()).toBe(200);
  await expect(page.getByText("TVT 계정 상태를 갱신했습니다.", { exact: true })).toBeVisible();
  expect(refreshBody).toEqual({ kind: "USER", expected_generation: generation, reason: "manual" });
  // This fixture returns a nonrotating renewal: current generation is stable.
  await expect.poll(async () => Number(await detail(page, "세션 버전").textContent())).toBe(generation);
  const browserMemory = await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })); expect(browserMemory).toEqual({ local: 0, session: 0 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth); expect(overflow).toBe(false);
  // Only synthetic fixture profile text is visible. Secrets and challenges
  // have settled and cleared before this explicitly owned visual QA capture.
  await expect(page.getByLabel("이메일", { exact: true })).toHaveValue("");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("account-profile.png"), fullPage: true });
  const logout = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/logout") && response.request().method() === "POST");
  await page.getByRole("button", { name: "TVT 로그아웃", exact: true }).click(); expect((await logout).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "현재 TVT 계정", exact: true })).toHaveCount(0);
  await expect(page.getByLabel("비밀번호", { exact: true })).toBeVisible();
  const retained = (await context.cookies(state.baseURL)).some(cookie => cookie.name === "__Host-wso-session" && state.cookies.some(original => original.name === cookie.name && original.value === cookie.value)); expect(retained).toBe(true);
  expect(methods.filter(item => item.path.endsWith("/refresh"))).toHaveLength(1);
  expect(methods.filter(item => item.path.startsWith("/api/auth/logout"))).toHaveLength(0);
  for (const [path, method] of [["/api/tvt/identities/challenges/image", "POST"], ["/api/tvt/identities/challenges/image/check", "POST"], ["/api/tvt/identities/login", "POST"], [`/api/tvt/identities/${identityId}/me`, "GET"], [`/api/tvt/identities/${identityId}/refresh`, "POST"], [`/api/tvt/identities/${identityId}/logout`, "POST"]]) expect(methods.some(item => item.path === path && item.method === method)).toBe(true);
  await page.goto(`${state.baseURL}/stores`); await expect(page).toHaveURL(/\/stores/); await expect(page.getByRole("link", { name: "다시 로그인", exact: true })).toHaveCount(0);
});
