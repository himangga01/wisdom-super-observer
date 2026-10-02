import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxyTvt } from "../src/lib/tvt/proxy";
import { accountClient } from "../src/lib/tvt/account-api-client";
const tenant = "10000000-0000-4000-8000-000000000001";
const origin = "https://app.example.test";
const config = { WSO_PUBLIC_ORIGIN: origin, WSO_OIDC_ISSUER: "https://id.example.test", WSO_OIDC_CLIENT_ID: "local-test", WSO_OIDC_CLIENT_SECRET: "local-test-secret", WSO_AUTH_EXCHANGE_KEY: "x".repeat(32), WSO_FLOW_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"), API_INTERNAL_ORIGIN: "http://127.0.0.1:8100" };
const consent = { version: "test-v1", status: "pending", decided_at: null, terms: { source_reference: "agreement/ServiceTerms_en.html", url: "https://policy.example.test/terms" }, privacy: { source_reference: "agreement/PrivacyStatement_en.html", url: "https://policy.example.test/privacy" } };
// Synthetic local fixture; no APK or provider acceptance claim.
const bootstrap = { selected_tenant_id: tenant, profile_id: "test", brand: "SuperLivePlus", region: "KR", locale: "en", timezone: "Asia/Seoul", supported_locales: ["en"], consent, identity: { state: "unlinked", accounts: [] }, menu: [{ id: "local-settings", label: "Settings", path: "/tvt/settings" }] };
function request(method = "GET", body?: unknown, headers?: Record<string, string>, query = `tenant_id=${tenant}`) {
  return new NextRequest(`${origin}/api/tvt/bootstrap?${query}`, { method, headers: { Origin: origin, Cookie: "__Host-wso-session=local-test-opaque; __Host-wso-csrf=local-test-csrf", "X-CSRF-Token": "local-test-csrf", "Content-Type": "application/json", ...headers }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
function fetcher(data: unknown, status = 200) { return vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(data), { status })); }
async function privateError(response: Response, status: number) { expect(response.status).toBe(status); expect(response.headers.get("cache-control")).toContain("no-store"); expect(response.headers.get("vary")).toBe("Cookie"); const data = await response.json(); expect(data).toHaveProperty("error.code"); expect(data).toHaveProperty("error.message"); expect(data).toHaveProperty("request_id"); return data; }
beforeEach(() => { Object.entries(config).forEach(([key, value]) => vi.stubEnv(key, value)); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it("restricts exact route, method, UUID and query before contacting the backend", async () => {
  const backend = fetcher(bootstrap);
  for (const [req, segments, status] of [[request(), ["..", "me"], 404], [request("POST", {}), ["bootstrap"], 405], [request("GET", undefined, {}, `tenant_id=${tenant}&tenant_id=${tenant}`), ["bootstrap"], 404], [request("GET", undefined, {}, "tenant_id=bad"), ["bootstrap"], 404], [request("GET", undefined, {}, `tenant_id=${tenant}&url=https://evil.test`), ["bootstrap"], 404]] as const) await privateError(await proxyTvt(req, [...segments], backend), status);
  expect(backend).not.toHaveBeenCalled();
});
it("rejects anonymous, foreign Origin, mismatched CSRF and strict invalid JSON bodies", async () => {
  const backend = fetcher(consent);
  await privateError(await proxyTvt(request("GET", undefined, { Cookie: "" }), ["bootstrap"], backend), 401);
  for (const headers of [{ Origin: "https://evil.test" }, { "X-CSRF-Token": "wrong" }, { Origin: "" }] as Record<string, string>[]) await privateError(await proxyTvt(request("POST", { version: "test-v1", decision: "accepted" }, headers), ["consent"], backend), 403);
  for (const body of [{ version: "test-v1", decision: "accepted", private: "extra" }, { version: "test-v1", decision: "other" }, { version: "x".repeat(5000), decision: "accepted" }]) await privateError(await proxyTvt(request("POST", body), ["consent"], backend), 422);
  await privateError(await proxyTvt(request("PUT", { locale: "en", timezone: "invalid-timezone" }), ["preferences"], backend), 422);
  await privateError(await proxyTvt(request("POST", {}, { "Content-Type": "text/plain" }), ["consent"], backend), 422);
  expect(backend).not.toHaveBeenCalled();
});
it("forwards only the configured operation, session and CSRF headers and projects nested private data", async () => {
  const backend = fetcher({ ...bootstrap, password: "never-public", identity: { ...bootstrap.identity, secret_handle: "never-public" }, consent: { ...consent, private: "never-public" } });
  const response = await proxyTvt(request(), ["bootstrap"], backend);
  expect(response.status).toBe(200); expect(await response.json()).toEqual(bootstrap);
  expect(response.headers.get("vary")).toBe("Cookie"); expect(response.headers.get("cache-control")).toContain("no-store");
  expect(backend).toHaveBeenCalledExactlyOnceWith(`http://127.0.0.1:8100/api/v1/tvt/bootstrap?tenant_id=${tenant}`, expect.objectContaining({ cache: "no-store", redirect: "error", method: "GET", headers: { Cookie: "__Host-wso-session=local-test-opaque" } }));
  const write = fetcher({ ...consent, status: "accepted", decided_at: "2026-10-02T00:00:00Z" });
  expect((await proxyTvt(request("POST", { version: "test-v1", decision: "accepted" }, { Authorization: "never-forward" }), ["consent"], write)).status).toBe(200);
  expect(write).toHaveBeenCalledExactlyOnceWith(`http://127.0.0.1:8100/api/v1/tvt/consent?tenant_id=${tenant}`, expect.objectContaining({ method: "POST", body: '{"version":"test-v1","decision":"accepted"}', headers: { Cookie: "__Host-wso-session=local-test-opaque", Origin: origin, "X-CSRF-Token": "local-test-csrf", "Content-Type": "application/json" } }));
});
it("projects the actual preferences response without inventing a bootstrap", async () => {
  const response = await proxyTvt(request("PUT", { locale: "en", timezone: "Asia/Seoul" }), ["preferences"], fetcher({ locale: "en", timezone: "Asia/Seoul", private: "never-public" }));
  expect(await response.json()).toEqual({ locale: "en", timezone: "Asia/Seoul" });
});
it("rejects a different tenant, unknown menu, unsafe policy or invalid public response", async () => {
  for (const data of [{ ...bootstrap, selected_tenant_id: "10000000-0000-4000-8000-000000000002" }, { ...bootstrap, menu: [{ id: "native", label: "Private", path: "https://evil.test" }] }, { ...bootstrap, consent: { ...consent, terms: { ...consent.terms, url: "javascript:alert(1)" } } }, { ...bootstrap, timezone: "invalid" }, { ...bootstrap, extra: "x".repeat(70000) }]) await privateError(await proxyTvt(request(), ["bootstrap"], fetcher(data)), 503);
});
it.each([401, 403, 404, 409, 422, 500, 503])("preserves canonical error envelope and correlation while sanitizing upstream %s", async status => {
  const requestId = "20000000-0000-4000-8000-000000000001";
  const response = await proxyTvt(request(), ["bootstrap"], fetcher({ error: { code: "private-code", message: "password=never-public", private: "never-public" }, request_id: requestId, private: "never-public" }, status));
  const data = await privateError(response, status === 500 ? 503 : status);
  expect(data.request_id).toBe(requestId); expect(JSON.stringify(data)).not.toContain("never-public"); expect(data.error.code).not.toBe("private-code");
});
it("sanitizes network exceptions without retry", async () => {
  const backend = vi.fn<typeof fetch>().mockRejectedValue(new Error("secret exception"));
  const data = await privateError(await proxyTvt(request(), ["bootstrap"], backend), 503);
  expect(JSON.stringify(data)).not.toContain("secret exception"); expect(backend).toHaveBeenCalledTimes(1);
});
it("rejects policy query data instead of sending a received secret URL to the browser", async () => {
  const data = { ...bootstrap, consent: { ...consent, terms: { ...consent.terms, url: "https://policy.example.test/terms?token=private" } } };
  await privateError(await proxyTvt(request(), ["bootstrap"], fetcher(data)), 503);
});
it("bounds the response body deadline even if the backend stream remains open", async () => {
  vi.useFakeTimers();
  const backend = vi.fn<typeof fetch>().mockResolvedValue(new Response(new ReadableStream<Uint8Array>()));
  const pending = proxyTvt(request(), ["bootstrap"], backend);
  await vi.advanceTimersByTimeAsync(10_001);
  await privateError(await pending, 503);
  expect(backend).toHaveBeenCalledTimes(1);
});

const identityId = "30000000-0000-4000-8000-000000000001";
const requestId = "20000000-0000-4000-8000-000000000001";
const identity = { identity_id: identityId, brand: "SuperLivePlus", region: "KR", state: "READY", generation: 7, request_id: requestId };
const login = { region: "KR", brand: "SuperLivePlus", mode: "email", account: "person@example.test", secret: "temporary-password" };
function accountRequest(path: string, method: string, body?: unknown, headers?: Record<string, string>, signal?: AbortSignal) {
  return new NextRequest(`${origin}/api/tvt/${path}?tenant_id=${tenant}`, { method, signal, headers: { Origin: origin, Cookie: "__Host-wso-session=local-test-opaque; __Host-wso-csrf=local-test-csrf", "X-CSRF-Token": "local-test-csrf", "Content-Type": "application/json", ...headers }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
}
it("admits exactly six account operations and strips private response fields", async () => {
  const profile = { ...identity, profile: { account_type: 3, user_name: "<script>text</script>", nickname: "", email: "", mobile: "", address: "", no_password: false, avatar_available: true, avatar_url: null } };
  for (const [path, method, body, data] of [
    ["identities/login", "POST", login, identity],
    ["identities/challenges/image", "POST", { region: "KR", brand: "SuperLivePlus" }, { challenge_id: identityId, media_type: "image/png", image_base64: "iVBORw0KGgo=", expires_in_seconds: 120, request_id: requestId }],
    ["identities/challenges/image/check", "POST", { region: "KR", brand: "SuperLivePlus", challenge_id: identityId, image_code: "1234" }, { checked: true, request_id: requestId }],
    [`identities/${identityId}/me`, "GET", undefined, profile],
    [`identities/${identityId}/refresh`, "POST", { kind: "USER", expected_generation: 7, reason: "manual" }, identity],
    [`identities/${identityId}/logout`, "POST", undefined, { identity_id: identityId, state: "CLOSED", upstream_outcome: "unknown", request_id: requestId }],
  ] as const) {
    const backend = fetcher({ ...data, raw_token: "private-never-echo" });
    const response = await proxyTvt(accountRequest(path, method, body), path.split("/"), backend);
    expect(response.status).toBe(200); expect(await response.json()).toEqual(data);
    expect(response.headers.get("x-request-id")).toBe(requestId);
    expect(backend).toHaveBeenCalledExactlyOnceWith(`http://127.0.0.1:8100/api/v1/tvt/${path}?tenant_id=${tenant}`, expect.objectContaining({ method, cache: "no-store", redirect: "error" }));
  }
});
it("rejects account selectors, unsupported token kinds and malformed bodies before forwarding", async () => {
  const backend = fetcher(identity);
  for (const path of ["identities/image-challenge", `identities/${identityId}/me/`, "identities/not-uuid/me", `identities/${identityId}%2fextra/me`]) await privateError(await proxyTvt(accountRequest(path, "GET"), path.split("/"), backend), 404);
  await privateError(await proxyTvt(accountRequest("identities/login", "GET"), ["identities", "login"], backend), 405);
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", { ...login, url: "https://evil.test" }), ["identities", "login"], backend), 422);
  await privateError(await proxyTvt(accountRequest(`identities/${identityId}/refresh`, "POST", { kind: "DEVICE", expected_generation: 7 }), ["identities", identityId, "refresh"], backend), 422);
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", { ...login, secret: "x".repeat(33000) }), ["identities", "login"], backend), 422);
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", {}, { Cookie: "" }), ["identities", "login"], backend), 401);
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", login, { Origin: "https://evil.test" }), ["identities", "login"], backend), 403);
  expect(backend).not.toHaveBeenCalled();
});
it.each([[409, "CHALLENGE_EXPIRED"], [409, "RENEWAL_OUTCOME_UNKNOWN"], [409, "ACCOUNT_DENIED"], [503, "auth_unavailable"], [504, "UNKNOWN_OUTCOME"], [401, "TOKEN_EXPIRED"], [401, "unauthenticated"], [403, "principal_not_provisioned"]] as const)("preserves safe account error semantics for %s %s", async (status, code) => {
  const response = await proxyTvt(accountRequest("identities/login", "POST", login), ["identities", "login"], fetcher({ error: { code, message: "private-password" }, request_id: requestId }, status));
  const data = await privateError(response, status);
  expect(data.error.code).toBe(code); expect(JSON.stringify(data)).not.toContain("private-password"); expect(data.error.message).not.toContain("약관이 변경");
});
it("uses one ten-second budget for request parsing and backend completion", async () => {
  vi.useFakeTimers(); let release!: () => void;
  const body = new ReadableStream<Uint8Array>({ start(controller) { release = () => { controller.enqueue(new TextEncoder().encode(JSON.stringify(login))); controller.close(); }; } });
  const req = new NextRequest(`${origin}/api/tvt/identities/login?tenant_id=${tenant}`, { method: "POST", body, headers: { Origin: origin, Cookie: "__Host-wso-session=session; __Host-wso-csrf=csrf", "X-CSRF-Token": "csrf", "Content-Type": "application/json" } });
  const backend = vi.fn<typeof fetch>().mockImplementation(() => new Promise<Response>(() => undefined));
  const pending = proxyTvt(req, ["identities", "login"], backend);
  await vi.advanceTimersByTimeAsync(9000); release(); await vi.advanceTimersByTimeAsync(1001);
  const data = await privateError(await pending, 504); expect(data.error.code).toBe("UNKNOWN_OUTCOME"); expect(backend).toHaveBeenCalledTimes(1);
});
it("refuses declared oversize account input and streamed oversize success envelopes", async () => {
  const backend = fetcher(identity);
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", login, { "Content-Length": "32769" }), ["identities", "login"], backend), 422);
  expect(backend).not.toHaveBeenCalled();
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", login), ["identities", "login"], fetcher({ ...identity, unused: "x".repeat(65536) })), 503);
});
it("keeps generated logout body absent through the browser client and strict proxy", async () => {
  vi.stubGlobal("window", { location: { origin } });
  const backend = fetcher({ identity_id: identityId, state: "CLOSED", upstream_outcome: "not_attempted", request_id: requestId });
  let hasBody: boolean | undefined; let contentType: string | null | undefined;
  vi.stubGlobal("fetch", async (request: Request) => {
    hasBody = request.body !== null; contentType = request.headers.get("content-type");
    const admitted = new NextRequest(request, { headers: { ...Object.fromEntries(request.headers), Origin: origin, Cookie: "__Host-wso-session=session; __Host-wso-csrf=csrf" } });
    return proxyTvt(admitted, ["identities", identityId, "logout"], backend);
  });
  expect(await accountClient("csrf").logout(tenant, identityId, new AbortController().signal)).toHaveProperty("state", "CLOSED");
  expect(hasBody).toBe(false); expect(contentType).toBeNull(); expect(backend).toHaveBeenCalledTimes(1);
});
function streamedLogout(stream: ReadableStream<Uint8Array>, signal?: AbortSignal, headers?: Record<string, string>) {
  return new NextRequest(`${origin}/api/tvt/identities/${identityId}/logout?tenant_id=${tenant}`, { method: "POST", body: stream, signal, headers: { Origin: origin, Cookie: "__Host-wso-session=session; __Host-wso-csrf=csrf", "X-CSRF-Token": "csrf", ...headers } });
}
it("accepts a settled zero-byte logout stream from the real Request adapter", async () => {
  const req = streamedLogout(new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array()); controller.close(); } }));
  expect(req.body).not.toBeNull();
  const backend = fetcher({ identity_id: identityId, state: "CLOSED", upstream_outcome: "unknown", request_id: requestId });
  const response = await proxyTvt(req, ["identities", identityId, "logout"], backend);
  expect(response.status).toBe(200); expect(await response.json()).toHaveProperty("state", "CLOSED");
  expect(backend).toHaveBeenCalledExactlyOnceWith(`http://127.0.0.1:8100/api/v1/tvt/identities/${identityId}/logout?tenant_id=${tenant}`, expect.objectContaining({ method: "POST", headers: { Cookie: "__Host-wso-session=session", Origin: origin, "X-CSRF-Token": "csrf" } }));
});
it.each([new Uint8Array([32]), new TextEncoder().encode("{}")])("rejects any positive logout stream byte before backend dispatch", async chunk => {
  const backend = fetcher({ identity_id: identityId, state: "CLOSED", upstream_outcome: "confirmed", request_id: requestId });
  const stream = new ReadableStream<Uint8Array>({ start(controller) { controller.enqueue(new Uint8Array()); controller.enqueue(chunk); controller.close(); } });
  await privateError(await proxyTvt(streamedLogout(stream), ["identities", identityId, "logout"], backend), 422);
  expect(backend).not.toHaveBeenCalled();
});
it("refuses a declared positive logout length even when the stream is empty", async () => {
  const backend = fetcher({});
  await privateError(await proxyTvt(streamedLogout(new ReadableStream<Uint8Array>({ start(controller) { controller.close(); } }), undefined, { "Content-Length": "1" }), ["identities", identityId, "logout"], backend), 422);
  expect(backend).not.toHaveBeenCalled();
});
it("bounds stalled logout body reads with the same total ten-second budget", async () => {
  vi.useFakeTimers(); const backend = fetcher({}); const cancel = vi.fn();
  const pending = proxyTvt(streamedLogout(new ReadableStream<Uint8Array>({ cancel })), ["identities", identityId, "logout"], backend);
  await vi.advanceTimersByTimeAsync(10001); const data = await privateError(await pending, 504);
  expect(data.error.code).toBe("UNKNOWN_OUTCOME"); expect(cancel).toHaveBeenCalledTimes(1); expect(backend).not.toHaveBeenCalled();
});
it("cancels an unfinished logout body read and does not dispatch or retry", async () => {
  const controller = new AbortController(); const backend = fetcher({}); const cancel = vi.fn();
  const pending = proxyTvt(streamedLogout(new ReadableStream<Uint8Array>({ cancel }), controller.signal), ["identities", identityId, "logout"], backend);
  controller.abort(); const data = await privateError(await pending, 504);
  expect(data.error.code).toBe("UNKNOWN_OUTCOME"); expect(cancel).toHaveBeenCalledTimes(1); expect(backend).not.toHaveBeenCalled();
});
it.each(["logout-byte", "stalled-logout", "cancelled-logout", "oversized-request", "oversized-response"])("finishes %s rejection when stream cancellation never settles", async boundary => {
  vi.useFakeTimers(); const cancel = vi.fn(() => new Promise<void>(() => undefined));
  const logout = boundary.endsWith("logout") || boundary === "logout-byte";
  const controller = new AbortController();
  const stream = new ReadableStream<Uint8Array>({ start(controller) { if (!boundary.endsWith("logout")) controller.enqueue(boundary === "logout-byte" ? new Uint8Array([32]) : new Uint8Array(65537)); }, cancel });
  const backend = boundary === "oversized-response" ? vi.fn<typeof fetch>().mockResolvedValue(new Response(stream)) : fetcher(identity);
  const req = logout ? streamedLogout(stream, controller.signal) : boundary === "oversized-request" ? new NextRequest(`${origin}/api/tvt/identities/login?tenant_id=${tenant}`, { method: "POST", body: stream, headers: { Origin: origin, Cookie: "__Host-wso-session=session; __Host-wso-csrf=csrf", "X-CSRF-Token": "csrf", "Content-Type": "application/json" } }) : accountRequest("identities/login", "POST", login);
  let completed: Response | undefined;
  const pending = proxyTvt(req, logout ? ["identities", identityId, "logout"] : ["identities", "login"], backend).then(response => { completed = response; return response; });
  if (boundary === "cancelled-logout") controller.abort();
  await vi.advanceTimersByTimeAsync(boundary === "cancelled-logout" ? 1 : 10001);
  expect(completed).toBeDefined();
  await privateError(await pending, boundary.endsWith("logout") ? 504 : boundary === "oversized-response" ? 503 : 422);
  expect(cancel).toHaveBeenCalledTimes(1); expect(backend).toHaveBeenCalledTimes(boundary === "oversized-response" ? 1 : 0);
});
it("rejects unknown account code/status pairs and non-null avatar URLs", async () => {
  await privateError(await proxyTvt(accountRequest("identities/login", "POST", login), ["identities", "login"], fetcher({ error: { code: "CHALLENGE_EXPIRED", message: "private" } }, 401)), 503);
  await privateError(await proxyTvt(accountRequest(`identities/${identityId}/me`, "GET"), ["identities", identityId, "me"], fetcher({ ...identity, profile: { account_type: 1, user_name: "", nickname: "", email: "", mobile: "", address: "", no_password: false, avatar_available: true, avatar_url: "https://private.test/avatar" } })), 503);
});
it("accepts the 90000 base64 image boundary while refusing oversized streamed or declared bodies", async () => {
  const path = "identities/challenges/image";
  const data = { challenge_id: identityId, media_type: "image/png", image_base64: "iVBORw0KGgo=".slice(0, 8) + "A".repeat(89992), expires_in_seconds: 120, request_id: requestId };
  expect((await proxyTvt(accountRequest(path, "POST", { region: "KR", brand: "SuperLivePlus" }), path.split("/"), fetcher(data))).status).toBe(200);
  const huge = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(data), { headers: { "content-length": "131073" } }));
  await privateError(await proxyTvt(accountRequest(path, "POST", { region: "KR", brand: "SuperLivePlus" }), path.split("/"), huge), 503);
});
it("propagates cancellation and does not repeat an uncertain account write", async () => {
  const controller = new AbortController(); let forwarded: AbortSignal | undefined;
  const backend = vi.fn<typeof fetch>().mockImplementation(async (_url, options) => { forwarded = options?.signal as AbortSignal; return new Response(new ReadableStream<Uint8Array>()); });
  const pending = proxyTvt(accountRequest("identities/login", "POST", login, {}, controller.signal), ["identities", "login"], backend);
  await vi.waitFor(() => expect(forwarded).toBeDefined()); controller.abort();
  await privateError(await pending, 504); expect(forwarded?.aborted).toBe(true); expect(backend).toHaveBeenCalledTimes(1);
});
