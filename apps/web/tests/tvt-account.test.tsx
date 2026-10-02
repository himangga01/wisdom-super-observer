// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { TvtShell } from "../src/features/tvt/shell/TvtShell";
import { SessionBoundary } from "../src/features/tvt/account/SessionBoundary";
import { publicBootstrap } from "../src/lib/tvt/api-client";
import { accountClient, loginSchema } from "../src/lib/tvt/account-api-client";
const tenant = "10000000-0000-4000-8000-000000000001";
const id = "30000000-0000-4000-8000-000000000001";
const otherId = "30000000-0000-4000-8000-000000000002";
const requestId = "20000000-0000-4000-8000-000000000001";
const account = { id, brand: "SuperLivePlus", region: "KR" };
const base = { selected_tenant_id: tenant, profile_id: "ui-test", brand: "SuperLivePlus", region: "KR", locale: "en", timezone: "Asia/Seoul", supported_locales: ["en"], consent: { version: "v1", status: "accepted", decided_at: "2026-10-02T00:00:00Z", terms: { source_reference: "agreement/ServiceTerms_en.html", url: "https://policy.test/terms" }, privacy: { source_reference: "agreement/PrivacyStatement_en.html", url: "https://policy.test/privacy" } }, identity: { state: "unlinked", accounts: [] }, menu: [{ id: "local-account", label: "Account", path: "/tvt/account" }] };
const identity = { identity_id: id, brand: "SuperLivePlus", region: "KR", state: "READY", generation: 7, request_id: requestId };
const profile = { ...identity, profile: { account_type: 91, user_name: "<img src=x onerror=alert(1)>", nickname: "Synthetic nickname", email: "synthetic@example.test", mobile: "", address: "", no_password: false, avatar_available: true, avatar_url: null } };
const image = { challenge_id: otherId, media_type: "image/png", image_base64: "iVBORw0KGgpJRU5ErkJggg==", expires_in_seconds: 120, request_id: requestId };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const error = (code: string, status: number) => json({ error: { code, message: "vendor-private-message" }, request_id: requestId }, status);
function mount(userId = "test-actor", tenantId = tenant) { return render(<TvtShell userId={userId} tenantId={tenantId} csrf="test-csrf" path="/tvt/account" />); }
function countryValue(locale: string) { return Array.from((screen.getByLabelText("국가 전화 코드") as HTMLSelectElement).options).find(option => option.value.startsWith(`${locale}:`))!.value; }
function fill(mode = "email") {
  if (mode === "phone") fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: countryValue("KR") } });
  fireEvent.change(screen.getByLabelText(mode === "email" ? "이메일" : "전화번호"), { target: { value: mode === "email" ? "synthetic@example.test" : "00101234" } });
  fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "ephemeral-password" } });
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it("constructs a lazy client and server renders without window access or personalized request", () => {
  vi.stubGlobal("window", undefined); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  expect(() => accountClient("csrf")).not.toThrow();
  expect(renderToString(<TvtShell userId="actor" tenantId={tenant} path="/tvt/account" />)).toContain("서비스 정보를 불러오는 중");
  expect(fetcher).not.toHaveBeenCalled();
});
it.each([
  { mode: "email", account: "wrong email" }, { mode: "phone", account: "+123" }, { secret: "a\u0000b" }, { secret: "😀" }, { image_code: "1234" }, { second_code: "x".repeat(257) },
])("rejects unsupported login input before credentials leave form memory: %j", changed => {
  expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "email", account: "a@example.test", secret: "x", ...changed }).success).toBe(false);
});
it("submits email and phone with trusted selection and never stores secrets in query or mutation cache", async () => {
  const cache = vi.spyOn(QueryClient.prototype, "getQueryCache");
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/login")) { bodies.push(await request.json()); return error("ACCOUNT_UPSTREAM_REJECTED", 502); }
    return json(base);
  });
  mount(); await screen.findByLabelText("비밀번호"); fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await screen.findByRole("alert"); expect(screen.getByLabelText("비밀번호")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone"); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies).toEqual([{ brand: "SuperLivePlus", region: "KR", mode: "email", account: "synthetic@example.test", secret: "ephemeral-password" }, { brand: "SuperLivePlus", region: "KR", mode: "phone", country_code: "82", account: "00101234", secret: "ephemeral-password" }]);
  expect(localStorage.length).toBe(0); expect(sessionStorage.length).toBe(0); expect(screen.queryByText("vendor-private-message")).toBeNull();
  for (const client of [...new Set(cache.mock.instances as QueryClient[])]) expect(JSON.stringify([client.getQueryCache().getAll().map(item => item.state.data), client.getMutationCache().getAll().map(item => item.state.variables)])).not.toContain("ephemeral-password");
});
it("consumes checked challenges, revokes images and requires a new challenge for later login", async () => {
  const create = vi.fn(() => "blob:owned-image"); const revoke = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
  const bodies: Record<string, unknown>[] = [];
  let imageRequests = 0;
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/image/check")) { bodies.push(await request.json()); return json({ checked: true, request_id: requestId }); }
    if (path.endsWith("/image")) { imageRequests++; return json(imageRequests === 1 ? image : { ...image, challenge_id: "30000000-0000-4000-8000-000000000003" }); }
    if (path.endsWith("/login")) { bodies.push(await request.json()); return error("ACCOUNT_UPSTREAM_REJECTED", 502); }
    return json(base);
  });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "이미지 확인 요청" }));
  expect(await screen.findByAltText("로그인 확인 이미지")).toHaveAttribute("src", "blob:owned-image");
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "이미지 코드 확인" }));
  await screen.findByText(/확인 이미지를 새로 요청/); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull(); expect(revoke).toHaveBeenCalledWith("blob:owned-image");
  fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await screen.findByRole("alert"); expect(bodies[0]).toHaveProperty("challenge_id", otherId); expect(bodies).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fill(); fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } }); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await waitFor(() => expect(bodies).toHaveLength(2)); expect(bodies[1]).toHaveProperty("challenge_id", "30000000-0000-4000-8000-000000000003");
  expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("");
});
it.each([["CHALLENGE_EXPIRED", 409], ["UNKNOWN_OUTCOME", 504]] as const)("retains the consumed-image requirement through a delayed same-scope %s recheck", async (code, status) => {
  const revoke = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:owned-recheck", revokeObjectURL: revoke }));
  let release!: (value: Response) => void; let checking = false; let images = 0;
  const loginBodies: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/image/check")) { checking = true; return error(code, status); }
    if (path.endsWith("/image")) { images++; return json({ ...image, challenge_id: images === 1 ? otherId : "30000000-0000-4000-8000-000000000003" }); }
    if (path.endsWith("/login")) { loginBodies.push(await request.json()); return error("ACCOUNT_UPSTREAM_REJECTED", 502); }
    if (checking) return new Promise<Response>(resolve => { release = resolve; });
    return json(base);
  });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fill(); fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "ephemeral-second" } });
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
  const password = screen.getByLabelText("비밀번호") as HTMLInputElement;
  const second = screen.getByLabelText("추가 확인 코드") as HTMLInputElement;
  fireEvent.click(screen.getByRole("button", { name: "이미지 코드 확인" }));
  await screen.findByText("현재 계정과 웹 로그인 권한을 확인합니다.");
  expect(password.value).toBe(""); expect(second.value).toBe(""); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull();
  expect(revoke).toHaveBeenCalledWith("blob:owned-recheck");
  await act(async () => { release(json(base)); }); await screen.findByLabelText("비밀번호");
  fill(); await act(async () => { fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); });
  expect(loginBodies).toHaveLength(0);
  expect(await screen.findByText("사용한 확인 이미지를 다시 사용할 수 없습니다. 로그인하려면 새 확인 이미지를 요청하세요.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fill(); fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await waitFor(() => expect(loginBodies).toHaveLength(1));
  expect(loginBodies[0]).toHaveProperty("challenge_id", "30000000-0000-4000-8000-000000000003");
  expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("");
});
it.each(["actor", "tenant", "profile", "region", "consent", "roster", "identity"])("isolates the non-secret consumed-image latch on %s scope change", async scope => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:scoped-image", revokeObjectURL: vi.fn() }));
  const authority = publicBootstrap({ ...base, identity: { state: "linked", accounts: [account, { ...account, id: otherId }] } }, tenant);
  const submissions: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/image/check")) return json({ checked: true, request_id: requestId });
    if (path.endsWith("/image")) return json(image);
    if (path.endsWith("/login")) { submissions.push(await request.json()); return error("ACCOUNT_UPSTREAM_REJECTED", 502); }
    return json({ ...profile, identity_id: path.includes(otherId) ? otherId : id });
  });
  const requery = async () => authority;
  const view = render(<SessionBoundary userId="first-actor" bootstrap={authority} csrf="csrf" requery={requery} />);
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "이미지 코드 확인" })); await screen.findByText(/확인 이미지를 새로 요청/);
  fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await screen.findByText("사용한 확인 이미지를 다시 사용할 수 없습니다. 로그인하려면 새 확인 이미지를 요청하세요.");
  expect(submissions).toHaveLength(0);
  if (scope === "identity") {
    fireEvent.change(screen.getByLabelText("연결된 TVT 계정"), { target: { value: id } });
    fill(); await act(async () => { fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); });
    expect(submissions).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("연결된 TVT 계정"), { target: { value: otherId } });
  }
  else {
    const next = { ...authority,
      ...(scope === "tenant" ? { selected_tenant_id: "10000000-0000-4000-8000-000000000002" } : {}),
      ...(scope === "profile" ? { profile_id: "other-profile" } : {}),
      ...(scope === "region" ? { region: "US", identity: { ...authority.identity, accounts: authority.identity.accounts.map(item => ({ ...item, region: "US" })) } } : {}),
      ...(scope === "consent" ? { consent: { ...authority.consent, version: "v2" } } : {}),
      ...(scope === "roster" ? { identity: { ...authority.identity, accounts: [authority.identity.accounts[1]] } } : {}),
    };
    view.rerender(<SessionBoundary userId={scope === "actor" ? "second-actor" : "first-actor"} bootstrap={next} csrf="csrf" requery={requery} />);
  }
  expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull();
  fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await waitFor(() => expect(submissions).toHaveLength(1)); expect(submissions[0]).not.toHaveProperty("challenge_id");
});
it("expires a challenge at 120 seconds and clears pending secrets on mode switch", async () => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:owned", revokeObjectURL: vi.fn() }));
  vi.stubGlobal("fetch", async (request: Request) => json(new URL(request.url).pathname.endsWith("/image") ? image : base));
  mount(); fireEvent.click(await screen.findByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  vi.useFakeTimers(); // The timer was scheduled before fake timers; expire against controlled wall clock.
  vi.setSystemTime(Date.now() + 120001); fill(); fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  expect(screen.getByRole("alert")).toHaveTextContent("만료"); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull();
  fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("");
});
it("shows public profile text and USER refresh generation, then closes only TVT even with unknown upstream logout", async () => {
  let closed = false; let generation = 7; const requests: { path: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/me")) return json({ ...profile, generation });
    if (path.endsWith("/refresh")) { requests.push({ path, body: await request.json() }); generation = 8; return json({ ...identity, generation }); }
    if (path.endsWith("/logout")) { requests.push({ path, body: undefined }); closed = true; return json({ identity_id: id, state: "CLOSED", upstream_outcome: "unknown", request_id: requestId }); }
    return json(closed ? base : { ...base, identity: { state: "linked", accounts: [account] } });
  });
  mount(); expect(await screen.findByText("Synthetic nickname")).toBeVisible(); expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeVisible(); expect(screen.queryByRole("img")).toBeNull();
  expect(screen.getByText("91")).toBeVisible(); fireEvent.click(screen.getByRole("button", { name: "TVT 세션 갱신" }));
  await screen.findByText("8"); expect(requests[0].body).toEqual({ kind: "USER", expected_generation: 7, reason: "manual" });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그아웃" }));
  await waitFor(() => expect(screen.queryByText("Synthetic nickname")).toBeNull()); expect(await screen.findByLabelText("비밀번호")).toBeVisible();
  expect(requests.map(item => item.path)).toEqual([`/api/tvt/identities/${id}/refresh`, `/api/tvt/identities/${id}/logout`]); expect(screen.queryByRole("link", { name: "다시 로그인" })).toBeNull();
});
it("ignores late profile and login completions after identity or actor switch", async () => {
  let late!: (value: Response) => void; let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === `/api/tvt/identities/${id}/me`) { signal = request.signal; return new Promise<Response>(resolve => { late = resolve; }); }
    if (path.endsWith("/me")) return Promise.resolve(json({ ...profile, identity_id: otherId, profile: { ...profile.profile, nickname: "Second account" } }));
    return Promise.resolve(json({ ...base, identity: { state: "linked", accounts: [account, { ...account, id: otherId }] } }));
  });
  const view = mount(); fireEvent.change(await screen.findByLabelText("연결된 TVT 계정"), { target: { value: otherId } });
  await screen.findByText("Second account"); expect(signal?.aborted).toBe(true);
  await act(async () => { late(json(profile)); }); expect(screen.queryByText("Synthetic nickname")).toBeNull();
  fill(); let lateLogin!: (value: Response) => void; let loginSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", (request: Request) => { if (new URL(request.url).pathname.endsWith("/login")) { loginSignal = request.signal; return new Promise<Response>(resolve => { lateLogin = resolve; }); } return Promise.resolve(json(base)); });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(lateLogin).toBeDefined());
  view.rerender(<TvtShell userId="second-actor" tenantId={tenant} csrf="csrf" path="/tvt/account" />); await screen.findByLabelText("비밀번호");
  await act(async () => { lateLogin(json(identity)); }); expect(loginSignal?.aborted).toBe(true); expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.queryByText("Synthetic nickname")).toBeNull();
});
it.each(["TOKEN_EXPIRED", "unauthenticated"])("checks authoritative bootstrap after %s before deciding web login was lost", async code => {
  let denied = false;
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/login")) { denied = true; return error(code, 401); }
    return denied && code === "unauthenticated" ? error("unauthenticated", 401) : json(base);
  });
  mount(); await screen.findByLabelText("비밀번호"); fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  if (code === "unauthenticated") { await screen.findByRole("link", { name: "다시 로그인" }); expect(screen.queryByLabelText("비밀번호")).toBeNull(); }
  else { await screen.findByRole("alert"); await waitFor(() => expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeEnabled()); expect(screen.queryByRole("link", { name: "다시 로그인" })).toBeNull(); }
});
it("reads current profile after unknown renewal without submitting another refresh", async () => {
  let renewals = 0; let profileReads = 0;
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/me")) { profileReads++; return json(profile); }
    if (path.endsWith("/refresh")) { renewals++; return error("RENEWAL_OUTCOME_UNKNOWN", 409); }
    return json({ ...base, identity: { state: "linked", accounts: [account] } });
  });
  mount(); await screen.findByText("Synthetic nickname"); fireEvent.click(screen.getByRole("button", { name: "TVT 세션 갱신" }));
  await screen.findByRole("alert"); await waitFor(() => expect(profileReads).toBe(2)); expect(renewals).toBe(1); expect(screen.getByRole("alert")).toHaveTextContent("다시 갱신하지");
});
it("uses the authoritative linked list after login and sends optional codes only once", async () => {
  let authenticated = false; let release!: (value: Response) => void; let submissions = 0; let body: Record<string, unknown> | undefined;
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/login")) { authenticated = true; submissions++; body = await request.json(); return json(identity); }
    if (path.endsWith("/me")) return json(profile);
    if (authenticated) return new Promise<Response>(resolve => { release = resolve; });
    return json(base);
  });
  const cache = vi.spyOn(QueryClient.prototype, "getQueryCache");
  mount(); await screen.findByLabelText("비밀번호"); fill(); fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "private-second-code" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(release).toBeDefined());
  expect(screen.queryByRole("heading", { name: "현재 TVT 계정" })).toBeNull();
  await act(async () => { release(json({ ...base, identity: { state: "linked", accounts: [account] } })); });
  await screen.findByText("Synthetic nickname"); expect(submissions).toBe(1); expect(body?.second_code).toBe("private-second-code");
  expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("");
  for (const client of [...new Set(cache.mock.instances as QueryClient[])]) expect(JSON.stringify(client.getQueryCache().getAll().map(item => item.state.data))).not.toContain("synthetic@example.test");
});
it("fails closed and clears account inputs when current consent changes during a request", async () => {
  let changed = false;
  vi.stubGlobal("fetch", async (request: Request) => {
    if (new URL(request.url).pathname.endsWith("/login")) { changed = true; return error("consent_version_changed", 409); }
    return json(changed ? { ...base, consent: { ...base.consent, version: "v2", status: "pending", decided_at: null } } : base);
  });
  mount(); await screen.findByLabelText("비밀번호"); fill(); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  await screen.findByText("약관 버전: v2"); expect(screen.queryByLabelText("비밀번호")).toBeNull(); expect(screen.queryByRole("heading", { name: "현재 TVT 계정" })).toBeNull();
});
it("focuses sanitized validation errors and cancels an outstanding image on unmount", async () => {
  let late!: (response: Response) => void; let signal: AbortSignal | undefined;
  vi.stubGlobal("fetch", (request: Request) => { if (new URL(request.url).pathname.endsWith("/image")) { signal = request.signal; return new Promise<Response>(resolve => { late = resolve; }); } return Promise.resolve(json(base)); });
  const create = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  const view = mount(); await screen.findByLabelText("비밀번호"); fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" }));
  expect(await screen.findByRole("alert")).toHaveFocus(); fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await waitFor(() => expect(late).toBeDefined());
  view.unmount(); await act(async () => { late(json(image)); }); expect(signal?.aborted).toBe(true); expect(create).not.toHaveBeenCalled();
});
it("clears idle secrets and scoped profile memory when the page is hidden for navigation", async () => {
  vi.stubGlobal("fetch", async (request: Request) => json(new URL(request.url).pathname.endsWith("/me") ? profile : { ...base, identity: { state: "linked", accounts: [account] } }));
  mount(); await screen.findByText("Synthetic nickname"); fill();
  const password = screen.getByLabelText("비밀번호") as HTMLInputElement;
  fireEvent(window, new Event("pagehide"));
  expect(password.value).toBe(""); expect(screen.queryByText("Synthetic nickname")).toBeNull(); expect(screen.queryByLabelText("비밀번호")).toBeNull();
});

it.each([{}, { country_code: null }, { country_code: "" }, { country_code: "+82" }, { country_code: "12345" }, { country_code: 82 }, { country_code: "８２" }, { country_code: "82", country_name: "Korea" }, { country_code: "82", account: "+1234" }, { country_code: "82", account: "1".repeat(33) }])("rejects closed phone country input %j", changes => {
  expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "phone", account: "00101234", secret: "x", ...changes }).success).toBe(false);
});
it("accepts local zeros and email omitted/null country while rejecting email country", () => {
  expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "phone", country_code: "0001", account: "0", secret: "x" }).success).toBe(true);
  for (const country of [{}, { country_code: null }]) expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "email", account: "a@example.test", secret: "x", ...country }).success).toBe(true);
  expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "email", country_code: "82", account: "a@example.test", secret: "x" }).success).toBe(false);
});
it("requires explicit source country selection with unique locale options and shared numeric codes", async () => {
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", async (request: Request) => { if (new URL(request.url).pathname.endsWith("/login")) { bodies.push(await request.json()); return error("ACCOUNT_UPSTREAM_REJECTED", 502); } return json(base); });
  mount(); await screen.findByLabelText("비밀번호");
  fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } });
  const selector = screen.getByLabelText("국가 전화 코드") as HTMLSelectElement;
  expect(selector).toHaveValue(""); expect(selector.options).toHaveLength(197);
  const options = Array.from(selector.options).slice(1);
  expect(new Set(options.map(item => item.value)).size).toBe(196);
  expect(options.find(item => item.value.startsWith("US:"))?.text).toContain("+1"); expect(options.find(item => item.value.startsWith("CA:"))?.text).toContain("+1");
  fireEvent.change(screen.getByLabelText("전화번호"), { target: { value: "00101234" } }); fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await screen.findByRole("alert"); expect(bodies).toHaveLength(0);
  fireEvent.change(selector, { target: { value: countryValue("CA") } }); fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(bodies).toHaveLength(1));
  expect(bodies[0]).toEqual({ brand: "SuperLivePlus", region: "KR", mode: "phone", country_code: "1", account: "00101234", secret: "x" });
  await waitFor(() => expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeEnabled());
  fireEvent.change(selector, { target: { value: countryValue("US") } }); fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(bodies).toHaveLength(2)); expect(bodies[1]).toEqual(bodies[0]);
});
it.each(["mode", "country"])("aborts an owned image and ignores late image completion after %s change", async change => {
  let release!: (response: Response) => void; let signal: AbortSignal | undefined;
  const create = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() }));
  vi.stubGlobal("fetch", async (request: Request) => { if (new URL(request.url).pathname.endsWith("/image")) { signal = request.signal; return new Promise<Response>(resolve => { release = resolve; }); } return json(base); });
  mount(); await screen.findByLabelText("비밀번호"); fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
  fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "synthetic-second" } });
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await waitFor(() => expect(release).toBeDefined());
  fireEvent.change(screen.getByLabelText(change === "mode" ? "로그인 방식" : "국가 전화 코드"), { target: { value: change === "mode" ? "email" : countryValue("CA") } });
  expect(signal?.aborted).toBe(true); expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("");
  await act(async () => { release(json(image)); }); expect(create).not.toHaveBeenCalled(); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull();
});
it("keeps consumed image freshness across country and mode changes", async () => {
  let logins = 0; const revoke = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:country", revokeObjectURL: revoke }));
  vi.stubGlobal("fetch", async (request: Request) => { const path = new URL(request.url).pathname; if (path.endsWith("/login")) { logins++; return error("ACCOUNT_UPSTREAM_REJECTED", 502); } if (path.endsWith("/image/check")) return json({ checked: true, request_id: requestId }); return json(path.endsWith("/image") ? image : base); });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } }); fireEvent.click(screen.getByRole("button", { name: "이미지 코드 확인" })); await screen.findByText(/확인 이미지를 새로 요청/);
  fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone"); fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: countryValue("CA") } }); fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await screen.findByText("사용한 확인 이미지를 다시 사용할 수 없습니다. 로그인하려면 새 확인 이미지를 요청하세요."); expect(logins).toBe(0); expect(revoke).toHaveBeenCalledWith("blob:country");
});

it.each([{ country_code: "82\n" }, { country_code: "82", account: "0012\n" }])("rejects trailing line separators in numeric phone fields %j", changes => {
  expect(loginSchema.safeParse({ brand: "SuperLivePlus", region: "KR", mode: "phone", account: "00101234", secret: "x", ...changes }).success).toBe(false);
});
it("renders unique localized source labels even when the source Chinese names repeat", async () => {
  document.documentElement.lang = "zh-CN";
  try {
    vi.stubGlobal("fetch", async () => json(base)); mount(); await screen.findByLabelText("비밀번호");
    fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } });
    const options = Array.from((screen.getByLabelText("국가 전화 코드") as HTMLSelectElement).options).slice(1);
    expect(options.find(item => item.value.startsWith("KR:"))?.text).toContain("韩国");
    expect(new Set(options.map(item => item.text)).size).toBe(196);
  } finally { document.documentElement.lang = ""; }
});

it.each(["mode", "country"])("aborts phone login and rejects late success after %s changes", async change => {
  let release!: (response: Response) => void; let signal: AbortSignal | undefined; let authorityReads = 0;
  vi.stubGlobal("fetch", async (request: Request) => { if (new URL(request.url).pathname.endsWith("/login")) { signal = request.signal; return new Promise<Response>(resolve => { release = resolve; }); } authorityReads++; return json(base); });
  mount(); await screen.findByLabelText("비밀번호"); fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(release).toBeDefined());
  const before = authorityReads;
  fireEvent.change(screen.getByLabelText(change === "mode" ? "로그인 방식" : "국가 전화 코드"), { target: { value: change === "mode" ? "email" : countryValue("CA") } });
  await act(async () => { release(json(identity)); });
  expect(signal?.aborted).toBe(true); expect(authorityReads).toBe(before); expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.queryByText("TVT 계정 로그인 상태를 확인했습니다.")).toBeNull();
});
it("country change clears an owned displayed challenge and all confirmation secrets", async () => {
  const revoke = vi.fn(); vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:country-change", revokeObjectURL: revoke }));
  vi.stubGlobal("fetch", async (request: Request) => json(new URL(request.url).pathname.endsWith("/image") ? image : base));
  mount(); await screen.findByLabelText("비밀번호"); fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fill("phone"); fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } }); fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "synthetic-second" } });
  const code = screen.getByLabelText("이미지 확인 코드") as HTMLInputElement;
  fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: countryValue("CA") } });
  expect(code.value).toBe(""); expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue(""); expect(screen.queryByAltText("로그인 확인 이미지")).toBeNull(); expect(revoke).toHaveBeenCalledWith("blob:country-change");
});

it.each([["country", "login"], ["country", "image"], ["country", "check"], ["mode", "login"], ["mode", "image"], ["mode", "check"]] as const)("preserves refilled inputs after %s changes while the old %s settles", async (change, kind) => {
    let release!: (response: Response) => void;
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:ownership-old", revokeObjectURL: vi.fn() }));
    vi.stubGlobal("fetch", async (request: Request) => {
      const path = new URL(request.url).pathname;
      const pending = kind === "login" ? path.endsWith("/login") : kind === "check" ? path.endsWith("/image/check") : path.endsWith("/image");
      if (pending) return new Promise<Response>(resolve => { release = resolve; });
      return json(path.endsWith("/image") ? image : base);
    });
    const view = mount(); await screen.findByLabelText("비밀번호");
    fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
    if (kind === "check") {
      fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
      fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "1234" } });
    }
    fireEvent.click(screen.getByRole("button", { name: kind === "login" ? "TVT 로그인" : kind === "check" ? "이미지 코드 확인" : "이미지 확인 요청" }));
    await waitFor(() => expect(release).toBeDefined());
    fireEvent.change(screen.getByLabelText(change === "mode" ? "로그인 방식" : "국가 전화 코드"), { target: { value: change === "mode" ? "email" : countryValue("CA") } });
    expect(screen.getByLabelText("비밀번호")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "replacement-password" } });
    fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "replacement-second" } });
    await act(async () => { release(json(kind === "image" ? image : kind === "check" ? { checked: true, request_id: requestId } : identity)); });
    expect(screen.getByLabelText("비밀번호")).toHaveValue("replacement-password"); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("replacement-second");
    view.unmount();
});
it("keeps a replacement login request and its form inputs owned when the old image settles", async () => {
  let releaseOld!: (response: Response) => void; let releaseNew!: (response: Response) => void;
  const bodies: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path.endsWith("/image")) return new Promise<Response>(resolve => { releaseOld = resolve; });
    if (path.endsWith("/login")) { bodies.push(await request.json()); return new Promise<Response>(resolve => { releaseNew = resolve; }); }
    return json(base);
  });
  mount(); await screen.findByLabelText("비밀번호"); fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await waitFor(() => expect(releaseOld).toBeDefined());
  fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: countryValue("CA") } });
  fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "replacement-password" } }); fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "replacement-second" } });
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그인" })); await waitFor(() => expect(releaseNew).toBeDefined());
  await act(async () => { releaseOld(json(image)); });
  expect(screen.getByLabelText("비밀번호")).toHaveValue("replacement-password"); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("replacement-second"); expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeDisabled();
  expect(bodies).toEqual([{ brand: "SuperLivePlus", region: "KR", mode: "phone", country_code: "1", account: "00101234", secret: "replacement-password", second_code: "replacement-second" }]);
  await act(async () => { releaseNew(error("ACCOUNT_UPSTREAM_REJECTED", 502)); });
  expect(screen.getByLabelText("비밀번호")).toHaveValue(""); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue(""); expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeEnabled();
});
it("preserves codes for a newly acquired challenge when an older rejected request finishes", async () => {
  let rejectOld!: (cause: Error) => void; let images = 0;
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:ownership-new", revokeObjectURL: vi.fn() }));
  vi.stubGlobal("fetch", async (request: Request) => {
    if (new URL(request.url).pathname.endsWith("/image")) { images++; if (images === 1) return new Promise<Response>((_, reject) => { rejectOld = reject; }); return json({ ...image, challenge_id: "30000000-0000-4000-8000-000000000003" }); }
    return json(base);
  });
  mount(); await screen.findByLabelText("비밀번호"); fireEvent.change(screen.getByLabelText("로그인 방식"), { target: { value: "phone" } }); fill("phone");
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await waitFor(() => expect(rejectOld).toBeDefined());
  fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: countryValue("CA") } });
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 요청" })); await screen.findByAltText("로그인 확인 이미지");
  fireEvent.change(screen.getByLabelText("비밀번호"), { target: { value: "replacement-password" } }); fireEvent.change(screen.getByLabelText("추가 확인 코드"), { target: { value: "replacement-second" } }); fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "replacement-image-code" } });
  await act(async () => { rejectOld(new Error("synthetic delayed private transport rejection")); });
  expect(screen.getByLabelText("비밀번호")).toHaveValue("replacement-password"); expect(screen.getByLabelText("추가 확인 코드")).toHaveValue("replacement-second"); expect(screen.getByLabelText("이미지 확인 코드")).toHaveValue("replacement-image-code"); expect(screen.getByAltText("로그인 확인 이미지")).toHaveAttribute("src", "blob:ownership-new");
});
