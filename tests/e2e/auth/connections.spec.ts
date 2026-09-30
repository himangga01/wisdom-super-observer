import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
const tenantA = "10000000-0000-4000-8000-000000000001";
const tenantB = "10000000-0000-4000-8000-000000000002";
async function login(page: Page, profile = "multi") {
  await page.goto("/api/auth/login");
  await page.getByRole("button", { name: profile, exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "내 매장", exact: true }),
  ).toBeVisible();
  await page.goto(`/connections?tenant_id=${tenantA}`);
}
async function create(page: Page, alias = "입구 카메라") {
  await page.getByRole("button", { name: "새 연결" }).click();
  await page.getByLabel("연결 이름").fill(alias);
  await page.getByLabel("사이트 / 주소").fill("본점");
  await page.getByLabel("아이디", { exact: true }).fill("fixture-user");
  await page.getByLabel("비밀번호", { exact: true }).fill("fixture-password");
  await page.getByRole("button", { name: "연결 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: alias, exact: true }),
  ).toBeVisible();
}
test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:9100/__test/reset");
});
test("owner creates zero-store connection and updates metadata, mappings and credentials before disconnect/delete", async ({
  page,
}) => {
  await login(page);
  await create(page);
  await expect(page.getByText("미확인", { exact: true })).toBeVisible();
  await expect(
    page.getByText("연결된 매장 없음", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "수정", exact: true }).click();
  await expect(page.getByLabel("아이디", { exact: true })).toHaveCount(0);
  await page.getByLabel("연결 이름").fill("수정된 연결");
  await page.getByLabel("강남점", { exact: true }).check();
  await page.getByLabel("홍대점", { exact: true }).check();
  await page.getByLabel("계정 정보 교체").check();
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  await page.getByLabel("아이디", { exact: true }).fill("replacement-user");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("replacement-password");
  await page.getByRole("button", { name: "변경 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "수정된 연결" }),
  ).toBeVisible();
  await expect(
    page.getByText("강남점 · 홍대점", { exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(await page.evaluate(() => Object.keys(sessionStorage))).toEqual([]);
  expect(await page.locator("body").innerText()).not.toContain(
    "replacement-password",
  );
  await page.getByRole("button", { name: "연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByText("미확인", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "연결 해제", exact: true }).click();
  await page.getByRole("button", { name: "해제 확인", exact: true }).click();
  await expect(page.getByText("해제됨", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "삭제", exact: true }).click();
  await page.getByRole("button", { name: "삭제 확인", exact: true }).click();
  await expect(
    page.getByText("등록된 연결이 없습니다.", { exact: true }),
  ).toBeVisible();
});
test("owner without stores can save connection before creating any store", async ({
  page,
}) => {
  await login(page, "ownerempty");
  await page.getByRole("button", { name: "새 연결" }).click();
  await expect(page.getByText(/선택할 매장이 없습니다/)).toBeVisible();
  await page.getByLabel("연결 이름").fill("매장 없이 연결");
  await page.getByLabel("사이트 / 주소").fill("기기");
  await page.getByLabel("연결 유형").selectOption("TVT_DEVICE");
  await page.getByLabel("아이디", { exact: true }).fill("u");
  await page.getByLabel("비밀번호", { exact: true }).fill("p");
  await page.getByRole("button", { name: "연결 저장", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "매장 없이 연결" }),
  ).toBeVisible();
});
test("nonowner and foreign tenants are denied while tenant switches and back refetch", async ({
  page,
}) => {
  await login(page, "staff");
  await expect(
    page.getByRole("heading", { name: "소유자 권한이 필요합니다" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "새 연결" })).toHaveCount(0);
  await page.goto(`/connections?tenant_id=${tenantB}`);
  await expect(
    page.getByRole("heading", { name: "연결을 찾을 수 없습니다" }),
  ).toBeVisible();
  await page.context().clearCookies();
  await login(page);
  await create(page);
  await page.getByLabel("조직 선택").selectOption(tenantB);
  await page.getByRole("button", { name: "조직 전환" }).click();
  await expect(
    page.getByText("등록된 연결이 없습니다.", { exact: true }),
  ).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "입구 카메라", exact: true }),
  ).toBeVisible();
  await page.goto(
    `/connections/${"30000000-0000-4000-8000-000000000099"}?tenant_id=${tenantA}`,
  );
  await expect(
    page.getByRole("heading", { name: "연결을 찾을 수 없습니다" }),
  ).toBeVisible();
});
test("generation conflict clears credentials, refetches current view and requires review without retry", async ({
  page,
  request,
}) => {
  await login(page);
  await create(page);
  await page.getByRole("button", { name: "수정", exact: true }).click();
  await page.getByLabel("계정 정보 교체").check();
  await page.getByLabel("아이디", { exact: true }).fill("new");
  await page.getByLabel("비밀번호", { exact: true }).fill("sensitive");
  await request.post("http://127.0.0.1:9100/__test/conflict");
  await page.getByRole("button", { name: "변경 저장", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "다른 곳에서 연결이 변경되었습니다",
  );
  await expect(page.getByRole("main").getByRole("alert")).toBeFocused();
  await expect(page.getByLabel("연결 이름")).toHaveValue("다른 곳에서 변경");
  await expect(page.getByLabel("계정 정보 교체")).not.toBeChecked();
  const stats = await (
    await request.get("http://127.0.0.1:9100/__test/connection-stats")
  ).json();
  expect(stats.writes).toBe(2);
});
test("mutation error clears password and proxy rejects missing CSRF/foreign Origin", async ({
  page,
  request,
}) => {
  await login(page);
  await page.getByRole("button", { name: "새 연결" }).click();
  await page.getByLabel("연결 이름").fill("a");
  await page.getByLabel("사이트 / 주소").fill("s");
  await page.getByLabel("아이디", { exact: true }).fill("u");
  await page.getByLabel("비밀번호", { exact: true }).fill("secret-input");
  await request.post(
    "http://127.0.0.1:9100/__test/fail-connections?status=503",
  );
  await page.getByRole("button", { name: "연결 저장", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "잠시 후 다시 시도",
  );
  await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  const response = await page
    .context()
    .request.post(`/api/connections?tenant_id=${tenantA}`, {
      headers: { Origin: "https://foreign.invalid" },
      data: { password: "secret-input" },
    });
  expect(response.status()).toBe(403);
  expect(await response.text()).not.toContain("secret-input");
});
test("connection reference layout and keyboard form work at desktop and mobile widths", async ({
  page,
  request,
}) => {
  mkdirSync("auth-state/ui-review", { recursive: true });
  for (const [name, width, height] of [
    ["desktop", 1440, 900],
    ["mobile", 390, 844],
  ] as const) {
    await page.context().clearCookies();
    await request.post("http://127.0.0.1:9100/__test/reset");
    await page.setViewportSize({ width, height });
    await login(page);
    await create(page);
    await page.screenshot({
      path: `auth-state/ui-review/connections-${name}.png`,
      fullPage: true,
      style: "nextjs-portal { display: none; }",
    });
    await page.getByRole("button", { name: "수정", exact: true }).click();
    await expect(page.getByLabel("연결 이름")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("사이트 / 주소")).toBeFocused();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `auth-state/ui-review/connection-form-${name}.png`,
      fullPage: true,
      style: "nextjs-portal { display: none; }",
    });
    await request.post(
      "http://127.0.0.1:9100/__test/fail-connections?status=503",
    );
    await page.getByRole("button", { name: "변경 저장", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    await page.screenshot({
      path: `auth-state/ui-review/connection-error-${name}.png`,
      fullPage: true,
      style: "nextjs-portal { display: none; }",
    });
  }
});

test("proxy enforces owner/tenant/store boundaries and rejects credential shape without saving", async ({
  page,
}) => {
  await login(page, "staff");
  expect(
    (
      await page.context().request.get(`/api/connections?tenant_id=${tenantA}`)
    ).status(),
  ).toBe(403);
  await page.context().clearCookies();
  await login(page);
  const csrf = (await page.context().cookies()).find(
    (cookie) => cookie.name === "__Host-wso-csrf",
  )!.value;
  const headers = { Origin: "https://localhost:3443", "X-CSRF-Token": csrf };
  const data = {
    kind: "TYCO_ACCOUNT",
    alias: "정상 이름",
    site: "사이트",
    username: "u",
    password: "p",
    store_ids: ["20000000-0000-4000-8000-000000000003"],
  };
  expect(
    (
      await page
        .context()
        .request.post(`/api/connections?tenant_id=${tenantA}`, {
          headers,
          data,
        })
    ).status(),
  ).toBe(404);
  expect(
    (
      await page
        .context()
        .request.post(`/api/connections?tenant_id=${tenantA}`, {
          headers,
          data: { ...data, store_ids: [], password: "" },
        })
    ).status(),
  ).toBe(422);
  expect(
    (
      await page
        .context()
        .request.post(`/api/connections?tenant_id=${tenantA}`, {
          headers: { Origin: "https://localhost:3443" },
          data,
        })
    ).status(),
  ).toBe(403);
  await page.reload();
  await expect(
    page.getByText("등록된 연결이 없습니다.", { exact: true }),
  ).toBeVisible();
});

test("connections revalidate after logout/back and expired writes redirect to login", async ({
  page,
  request,
}) => {
  await login(page);
  await create(page);
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(page).toHaveURL(/signed_out=1/);
  await page.goBack();
  await expect(page).toHaveURL(/expired=1/);
  await login(page);
  await page.getByRole("button", { name: "새 연결" }).click();
  await page.getByLabel("연결 이름").fill("만료 요청");
  await page.getByLabel("사이트 / 주소").fill("s");
  await page.getByLabel("아이디", { exact: true }).fill("u");
  await page.getByLabel("비밀번호", { exact: true }).fill("p");
  await request.post("http://127.0.0.1:9100/__test/expire");
  await page.getByRole("button", { name: "연결 저장", exact: true }).click();
  await expect(page).toHaveURL(/expired=1/);
});

for (const [status, message] of [
  [403, "조직 소유자"],
  [404, "찾을 수 없습니다"],
  [422, "입력 내용을 확인"],
] as const) {
  test(`connection mutation ${status} explains failure and clears credentials`, async ({
    page,
    request,
  }) => {
    await login(page);
    await page.getByRole("button", { name: "새 연결" }).click();
    await page.getByLabel("연결 이름").fill("오류 연결");
    await page.getByLabel("사이트 / 주소").fill("s");
    await page.getByLabel("아이디", { exact: true }).fill("u");
    await page.getByLabel("비밀번호", { exact: true }).fill("never-retain");
    await request.post(
      `http://127.0.0.1:9100/__test/fail-connections?status=${status}`,
    );
    await page.getByRole("button", { name: "연결 저장", exact: true }).click();
    await expect(page.getByRole("main").getByRole("alert")).toContainText(
      message,
    );
    await expect(page.getByLabel("비밀번호", { exact: true })).toHaveValue("");
  });
}

test("connection list outage offers a safe explicit retry", async ({
  page,
  request,
}) => {
  await login(page);
  await request.post(
    "http://127.0.0.1:9100/__test/fail-connections?status=503",
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "연결을 불러올 수 없습니다" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
  expect(await page.locator("body").innerText()).not.toContain(
    "fixture-private-detail",
  );
});
