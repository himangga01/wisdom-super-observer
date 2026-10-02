// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { QueryClient } from "@tanstack/react-query";
import { ServiceShell } from "../src/components/service-shell";
import { TvtShell } from "../src/features/tvt/shell/TvtShell";
import { startupClient, type Bootstrap } from "../src/lib/tvt/api-client";
import { startupKey } from "../src/lib/tvt/query-provider";
const tenant = "10000000-0000-4000-8000-000000000001";
const otherTenant = "10000000-0000-4000-8000-000000000002";
// Local test only: complete synthetic DTO derived from the generated startup contract.
const base: Bootstrap = { selected_tenant_id: tenant, profile_id: "local-test", brand: "SuperLivePlus", region: "KR", locale: "en", timezone: "Asia/Seoul", supported_locales: ["en", "zh-Hans"], consent: { version: "test-v1", status: "pending", decided_at: null, terms: { source_reference: "agreement/ServiceTerms_en.html", url: "https://policies.example.test/terms" }, privacy: { source_reference: "agreement/PrivacyStatement_en.html", url: "https://policies.example.test/privacy" } }, identity: { state: "unlinked", accounts: [] }, menu: [{ id: "local-settings", label: "Settings", path: "/tvt/settings" }] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
function mount(path = "/tvt") { return render(<TvtShell userId="local-test-user" tenantId={tenant} csrf="local-test-csrf" path={path} />); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it("server renders the admitted real shell without a browser global or personalized fetch", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const browserWindow = window;
  vi.stubGlobal("window", undefined);
  try {
    const html = renderToString(<TvtShell userId="local-test-user" tenantId={tenant} csrf="local-test-csrf" />);
    expect(html).toContain("서비스 정보를 불러오는 중입니다.");
    expect(fetcher).not.toHaveBeenCalled();
  } finally { vi.stubGlobal("window", browserWindow); }
});
it.each(["readback", "mutation"] as const)("cancels and clears a loaded scope on 403 %s without restoring late data", async deniedAt => {
  const cancel = vi.spyOn(QueryClient.prototype, "cancelQueries");
  const cacheAccess = vi.spyOn(QueryClient.prototype, "getQueryCache");
  const clear = vi.spyOn(QueryClient.prototype, "clear");
  let readbackDenied = false;
  let lateResponse!: (response: Bootstrap) => void;
  let lateSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", async (request: Request) => {
    if (request.method === "PUT") { readbackDenied = true; return deniedAt === "mutation" ? json({}, 403) : json(await request.json()); }
    if (readbackDenied) return json({}, 403);
    return json(base);
  });
  mount("/tvt/settings"); await screen.findByText("지역: KR");
  const activeClient = cacheAccess.mock.instances[0] as QueryClient;
  // A second real query in this scope represents another pending personalized read.
  const lateQuery = activeClient.fetchQuery({ queryKey: ["tvt", "local-test-user", tenant, "pending-read"], queryFn: ({ signal }) => { lateSignal = signal; return new Promise<Bootstrap>(resolve => { lateResponse = resolve; }); } }).catch(() => undefined);
  fireEvent.click(screen.getByRole("button", { name: "설정 저장" }));
  await screen.findByRole("alert");
  await waitFor(() => expect(screen.queryByText("지역: KR")).toBeNull());
  expect(cancel).toHaveBeenCalled();
  expect(clear.mock.instances).toContain(activeClient);
  expect(activeClient.getQueryData(startupKey({ userId: "local-test-user", tenantId: tenant }))).toBeUndefined();
  expect(screen.queryByLabelText("시간대")).toBeNull();
  expect(screen.queryByText("약관 버전: test-v1")).toBeNull();
  expect(lateSignal?.aborted).toBe(true);
  lateResponse(base); await lateQuery;
  expect(activeClient.getQueryCache().getAll().every(query => query.state.data === undefined)).toBe(true);
  expect(screen.queryByText("지역: KR")).toBeNull();
});
it("labels Korean interface copy as Korean while preserving the selected date locale", async () => {
  vi.stubGlobal("fetch", async () => json({ ...base, locale: "zh-Hans", consent: { ...base.consent, status: "accepted", decided_at: "2026-10-02T00:00:00Z" } }));
  const view = mount(); await screen.findByText("지역: KR");
  expect(view.container.querySelector(".tvt-shell")).toHaveAttribute("lang", "ko");
  expect(view.container.querySelector("time")).toHaveTextContent(new Intl.DateTimeFormat("zh-Hans", { timeZone: "Asia/Seoul", dateStyle: "medium", timeStyle: "short" }).format(new Date("2026-10-02T00:00:00Z")));
});
it("uses the generated consent write operation in the browser client", async () => {
  vi.stubGlobal("fetch", async (request: Request) => { expect(request.method).toBe("POST"); expect(await request.json()).toEqual({ version: "test-v1", decision: "accepted" }); return json({ ...base.consent, status: "accepted", decided_at: "2026-10-02T00:00:00Z" }); });
  expect(await startupClient("local-test-csrf").consent(tenant, { version: "test-v1", decision: "accepted" }, new AbortController().signal)).toHaveProperty("status", "accepted");
});
it("opens SuperLivePlus only for the existing selected tenant", () => {
  render(<ServiceShell csrf="local-test-csrf" connectionTenant="10000000-0000-4000-8000-000000000001"><p>Content</p></ServiceShell>);
  expect(screen.getAllByRole("link", { name: /SuperLivePlus/ })[0]).toHaveAttribute("href", "/tvt?tenant_id=10000000-0000-4000-8000-000000000001");
});
it("never fetches personalized data while signed out or without a selected tenant", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const view = render(<TvtShell />);
  expect(screen.getByRole("link", { name: "로그인" })).toHaveAttribute("href", "/api/auth/login");
  view.rerender(<TvtShell userId="local-test-user" />);
  expect(screen.getByRole("link", { name: "내 매장으로 이동" })).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});
it.each(["accepted", "declined"] as const)("saves first-run %s with current version then reads authoritative bootstrap", async decision => {
  let authoritative = base;
  const requests: Request[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    requests.push(request);
    if (request.method === "POST") { expect(await request.json()).toEqual({ version: "test-v1", decision }); authoritative = { ...base, consent: { ...base.consent, status: decision, decided_at: "2026-10-02T00:00:00Z" } }; return json(authoritative.consent); }
    return json(authoritative);
  });
  mount(); fireEvent.click(await screen.findByRole("button", { name: decision === "accepted" ? "동의" : "거절" }));
  await screen.findByText(decision === "accepted" ? "현재 약관에 동의했습니다." : /동의를 거절했습니다/);
  expect(requests.map(request => new URL(request.url).pathname)).toEqual(["/api/tvt/bootstrap", "/api/tvt/consent", "/api/tvt/bootstrap"]);
  expect(requests[1].headers.get("x-csrf-token")).toBe("local-test-csrf");
  expect(screen.queryByRole("link", { name: /Tyco|카메라|원격/ })).toBeNull();
});
it("refreshes a changed consent version after 409 without accepting optimistically", async () => {
  let changed = false;
  vi.stubGlobal("fetch", async (request: Request) => { if (request.method === "POST") { changed = true; return json({ error: { code: "consent_version_changed", message: "private" } }, 409); } return json(changed ? { ...base, consent: { ...base.consent, version: "test-v2" } } : base); });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "동의" }));
  await screen.findByText("약관 버전: test-v2");
  expect(screen.getByRole("alert")).toHaveTextContent("약관이 변경");
  expect(screen.queryByText("현재 약관에 동의했습니다.")).toBeNull();
});
it.each(["/tvt/native-intent", "/tvt/settings"])("rejects a deep link without an authoritative menu entry: %s", async path => {
  vi.stubGlobal("fetch", async () => json({ ...base, menu: [] })); mount(path);
  expect(await screen.findByRole("alert")).toHaveTextContent("이 페이지를 사용할 수 없습니다");
  expect(screen.getByRole("link", { name: "SuperLivePlus 홈으로 이동" })).toHaveAttribute("href", `/tvt?tenant_id=${tenant}`);
  expect(screen.queryByLabelText("언어")).toBeNull();
});
it("preserves failed settings inputs and confirms locale/timezone from refreshed bootstrap", async () => {
  let current = base; let writes = 0;
  vi.stubGlobal("fetch", async (request: Request) => {
    if (request.method === "PUT") { writes++; const body = await request.json(); if (writes === 1) return json({ error: { message: "raw-private" } }, 422); current = { ...base, ...body }; return json(body); }
    return json(current);
  });
  mount("/tvt/settings");
  fireEvent.change(await screen.findByLabelText("언어"), { target: { value: "zh-Hans" } });
  fireEvent.change(screen.getByLabelText("시간대"), { target: { value: "Europe/London" } });
  fireEvent.click(screen.getByRole("button", { name: "설정 저장" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("언어")).toHaveValue("zh-Hans"); expect(screen.getByLabelText("시간대")).toHaveValue("Europe/London");
  expect(screen.queryByText("raw-private")).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "설정 저장" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "설정 저장" })); await screen.findByText("설정을 저장했습니다.");
  expect(screen.getByText(/언어: zh-Hans/)).toHaveTextContent("Europe/London");
});
it("drops old scope and late replies during a tenant switch", async () => {
  let oldReply!: (response: Response) => void; let oldSignal: AbortSignal | null = null;
  vi.stubGlobal("fetch", (request: Request) => { if (new URL(request.url).searchParams.get("tenant_id") === tenant) { oldSignal = request.signal; return new Promise<Response>(resolve => { oldReply = resolve; }); } return Promise.resolve(json({ ...base, selected_tenant_id: otherTenant, region: "US" })); });
  const view = mount(); await waitFor(() => expect(oldReply).toBeDefined());
  view.rerender(<TvtShell userId="local-test-user" tenantId={otherTenant} />);
  await screen.findByText("지역: US"); oldReply(json(base));
  await waitFor(() => expect(oldSignal?.aborted).toBe(true));
  expect(screen.queryByText("지역: KR")).toBeNull();
  expect(startupKey({ userId: "one", tenantId: tenant })).not.toEqual(startupKey({ userId: "two", tenantId: tenant }));
});
it("clears personalized content on logout and unauthorized replies", async () => {
  vi.stubGlobal("fetch", async () => json(base));
  const view = render(<><form action="/api/auth/logout"><button>Logout test</button></form><TvtShell userId="local-test-user" tenantId={tenant} /></>);
  await screen.findByText("지역: KR");
  fireEvent.submit(screen.getByRole("button", { name: "Logout test" }).closest("form")!);
  await screen.findByRole("link", { name: "다시 로그인" }); expect(screen.queryByText("지역: KR")).toBeNull();
  view.unmount(); vi.stubGlobal("fetch", async () => json({}, 401)); mount();
  await screen.findByRole("link", { name: "다시 로그인" }); expect(screen.queryByText("지역: KR")).toBeNull();
});
it("renders linked state factually and an unavailable profile safely", async () => {
  vi.stubGlobal("fetch", async () => json({ ...base, identity: { state: "linked", accounts: [{ id: otherTenant, brand: "SuperLivePlus", region: "KR" }] } }));
  const view = mount(); await screen.findByText("연결된 TVT 계정이 있습니다.");
  view.unmount(); vi.stubGlobal("fetch", async () => json({}, 503)); mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("서비스 정보를 불러올 수 없습니다");
});
it("retains settings input when the authoritative read after saving is unavailable", async () => {
  let written = false;
  vi.stubGlobal("fetch", async (request: Request) => {
    if (request.method === "PUT") { written = true; return json(await request.json()); }
    return written ? json({}, 503) : json(base);
  });
  mount("/tvt/settings"); fireEvent.change(await screen.findByLabelText("시간대"), { target: { value: "Europe/London" } });
  fireEvent.click(screen.getByRole("button", { name: "설정 저장" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("시간대")).toHaveValue("Europe/London");
  expect(screen.queryByText("설정을 저장했습니다.")).toBeNull();
});

it("admits registered account navigation, preserves tenant and gates login on current consent", async () => {
  let accepted = false;
  vi.stubGlobal("fetch", async (request: Request) => {
    if (new URL(request.url).pathname.endsWith("/consent")) { accepted = true; return json({ ...base.consent, status: "accepted", decided_at: "2026-10-02T00:00:00Z" }); }
    return json({ ...base, menu: [...base.menu, { id: "local-account", label: "Account", path: "/tvt/account" }], consent: accepted ? { ...base.consent, status: "accepted", decided_at: "2026-10-02T00:00:00Z" } : base.consent });
  });
  mount("/tvt/account");
  expect(await screen.findByRole("link", { name: "계정" })).toHaveAttribute("href", `/tvt/account?tenant_id=${tenant}`);
  expect(screen.queryByLabelText("비밀번호")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "동의" }));
  expect(await screen.findByLabelText("비밀번호")).toBeVisible();
});
it("rejects mismatched account menu labels and duplicate registrations", async () => {
  for (const menu of [[{ id: "local-account", label: "Settings", path: "/tvt/account" }], [{ id: "local-account", label: "Account", path: "/tvt/account" }, { id: "local-account", label: "Account", path: "/tvt/account" }]]) {
    vi.stubGlobal("fetch", async () => json({ ...base, menu })); const view = mount("/tvt/account");
    expect(await screen.findByRole("alert")).toHaveTextContent("서비스 정보를 불러올 수 없습니다"); view.unmount();
  }
});
