import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxyTvt } from "../src/lib/tvt/proxy";
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
afterEach(() => { vi.unstubAllEnvs(); vi.useRealTimers(); });
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
