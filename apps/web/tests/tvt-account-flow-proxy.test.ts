import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxyTvt } from "../src/lib/tvt/proxy";
import { accountFlowClient, flowCodeSchema, flowStartSchema, flowViewSchema, safeFlowError } from "../src/lib/tvt/flow-api-client";
const tenant = "10000000-0000-4000-8000-000000000001";
const flow = "20000000-0000-4000-8000-000000000001";
const requestId = "30000000-0000-4000-8000-000000000001";
const origin = "https://app.example.test";
const config = { WSO_PUBLIC_ORIGIN: origin, WSO_OIDC_ISSUER: "https://id.example.test", WSO_OIDC_CLIENT_ID: "local-test", WSO_OIDC_CLIENT_SECRET: "local-test-secret", WSO_AUTH_EXCHANGE_KEY: "x".repeat(32), WSO_FLOW_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"), API_INTERNAL_ORIGIN: "http://127.0.0.1:8100" };
const reference = { region: "KR", brand: "SuperLivePlus", purpose: "register", flow_id: flow };
const start = { region: "KR", brand: "SuperLivePlus", purpose: "register", mode: "email", account: "person@example.test" };
const view = { ...reference, request_id: requestId, state: "CREATED", exists: null, image: null, error_code: null, expires_in_seconds: null, resend_wait_seconds: null, return_to_login: false, automatic_retry_permitted: false };
const bodies = { start, state: reference, existence: reference, image: reference, "issue-code": reference, register: { ...reference, password: "private-password", dynamic_code: "123456" }, recover: { ...reference, purpose: "recover", new_password: "private-password", dynamic_code: "123456" }, cancel: reference };
function request(op: string, body: unknown = bodies[op as keyof typeof bodies], headers: Record<string, string> = {}, query = `tenant_id=${tenant}`, method = "POST", signal?: AbortSignal) {
  return new NextRequest(`${origin}/api/tvt/account-flows/${op}?${query}`, { method, signal, headers: { Origin: origin, Cookie: "__Host-wso-session=opaque; __Host-wso-csrf=csrf", "X-CSRF-Token": "csrf", "Content-Type": "application/json", ...headers }, ...(method === "GET" ? {} : { body: JSON.stringify(body) }) });
}
const backend = (value: unknown = view, status = 200) => vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(value), { status }));
beforeEach(() => Object.entries(config).forEach(([k, v]) => vi.stubEnv(k, v)));
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it.each(Object.entries(bodies))("forwards fixed %s once with private cookies and CSRF and returns closed view", async (op, body) => {
  const upstream = backend({ ...view, purpose: body.purpose });
  const result = await proxyTvt(request(op, body), ["account-flows", op], upstream);
  expect(result.status).toBe(200);
  expect(await result.json()).toEqual({ ...view, purpose: body.purpose });
  expect(upstream).toHaveBeenCalledExactlyOnceWith(`http://127.0.0.1:8100/api/v1/tvt/account-flows/${op}?tenant_id=${tenant}`, expect.objectContaining({ method: "POST", cache: "no-store", redirect: "error", body: JSON.stringify(body), headers: { Cookie: "__Host-wso-session=opaque", Origin: origin, "X-CSRF-Token": "csrf", "Content-Type": "application/json" } }));
  expect(result.headers.get("cache-control")).toContain("no-store"); expect(result.headers.get("vary")).toBe("Cookie");
});
it("authenticates before malformed secret body and rejects CSRF before parsing", async () => {
  const upstream = backend();
  expect((await proxyTvt(request("register", { password: "x".repeat(40000) }, { Cookie: "" }), ["account-flows", "register"], upstream)).status).toBe(401);
  expect((await proxyTvt(request("start", {}, { Origin: "https://evil.test" }), ["account-flows", "start"], upstream)).status).toBe(403);
  expect(upstream).not.toHaveBeenCalled();
});
it("denies extra paths, methods, duplicate query, oversized and authority inputs", async () => {
  const upstream = backend();
  for (const [req, segments, status] of [
    [request("dispatch"), ["account-flows", "dispatch"], 404],
    [request("start", start, {}, undefined, "GET"), ["account-flows", "start"], 405],
    [request("start", start, {}, `tenant_id=${tenant}&tenant_id=${tenant}`), ["account-flows", "start"], 404],
    [request("start", { ...start, actor_id: tenant }), ["account-flows", "start"], 422],
    [request("start", { ...start, country_code: null }), ["account-flows", "start"], 422],
    [request("register", { ...bodies.register, password: "x".repeat(40000) }), ["account-flows", "register"], 422],
    [request("register", { ...bodies.register, purpose: "recover" }), ["account-flows", "register"], 422],
  ] as const) expect((await proxyTvt(req, [...segments], upstream)).status).toBe(status);
  expect(upstream).not.toHaveBeenCalled();
});
it("rejects inconsistent selection, purpose, flow reference and public state invariants", async () => {
  for (const patch of [{ region: "other" }, { purpose: "recover" }, { flow_id: tenant }, { exists: false }, { state: "COMPLETE" }, { state: "UNKNOWN_OUTCOME", automatic_retry_permitted: true }, { state: "IMAGE_REQUIRED" }, { idCode: "private" }, { request_id: "https://evil.test" }]) {
    const result = await proxyTvt(request("state"), ["account-flows", "state"], backend({ ...view, ...patch }));
    expect(result.status).toBe(503); expect(JSON.stringify(await result.json())).not.toContain("private");
  }
});
it("rejects a backend error whose header and body request ids disagree", async () => {
  const upstream = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({ error: { code: "FLOW_EXPIRED", message: "private" }, request_id: requestId }), { status: 409, headers: { "X-Request-ID": tenant } }));
  expect((await proxyTvt(request("state"), ["account-flows", "state"], upstream)).status).toBe(503);
});
it("preserves strict false existence and complete return-to-login without auto retry", async () => {
  for (const patch of [{ state: "EXISTENCE", exists: false }, { state: "COMPLETE", return_to_login: true }, { state: "UNKNOWN_OUTCOME" }]) {
    const upstream = backend({ ...view, ...patch }); const result = await proxyTvt(request("state"), ["account-flows", "state"], upstream);
    expect(result.status).toBe(200); expect(await result.json()).toEqual({ ...view, ...patch }); expect(upstream).toHaveBeenCalledTimes(1);
  }
});
it("allows bounded image views for image and issue-code without globally enlarging responses", async () => {
  const image = { challenge_id: tenant, generation: 1, media_type: "image/png", image_base64: Buffer.alloc(60000, 1).toString("base64") };
  for (const op of ["image", "issue-code"]) expect((await proxyTvt(request(op), ["account-flows", op], backend({ ...view, state: "IMAGE_REQUIRED", image }))).status).toBe(200);
  expect((await proxyTvt(request("state"), ["account-flows", "state"], backend({ ...view, state: "IMAGE_REQUIRED", image }))).status).toBe(503);
});
it("maps only typed safe error envelopes and correlation and never retries", async () => {
  const upstream = backend({ error: { code: "FLOW_EXPIRED", message: "private-password" }, request_id: requestId }, 409);
  const result = await proxyTvt(request("register"), ["account-flows", "register"], upstream);
  expect(result.status).toBe(409); const data = await result.json(); expect(data.error.code).toBe("FLOW_EXPIRED"); expect(data.request_id).toBe(requestId); expect(JSON.stringify(data)).not.toContain("private-password"); expect(upstream).toHaveBeenCalledTimes(1);
  expect((await proxyTvt(request("register"), ["account-flows", "register"], backend({ error: { code: "FLOW_EXPIRED" }, request_id: requestId }, 502))).status).toBe(503);
});
it("bounds stalled body and nonsettling cancel cleanup to original ten seconds", async () => {
  vi.useFakeTimers();
  const upstream = vi.fn<typeof fetch>().mockResolvedValue(new Response(new ReadableStream<Uint8Array>({ cancel: () => new Promise(() => {}) })));
  const pending = proxyTvt(request("register"), ["account-flows", "register"], upstream);
  await vi.advanceTimersByTimeAsync(10001);
  const result = await pending; expect(result.status).toBe(504); expect((await result.json()).error.code).toBe("UNKNOWN_OUTCOME"); expect(upstream).toHaveBeenCalledTimes(1);
});
it.each([["ACCOUNT_SCOPE_INVALID", 422], ["ACCOUNT_CANCELLED", 409], ["ACCOUNT_QUARANTINED", 409], ["FLOW_PURPOSE_INVALID", 422], ["FLOW_RATE_LIMITED", 429], ["SESSION_BUSY", 409], ["CAPABILITY_UNSUPPORTED", 409], ["FORBIDDEN", 403], ["RATE_LIMITED", 429], ["UPSTREAM_TIMEOUT", 504]] as const)("preserves reviewed flow RPC failure %s/%s", (code, status) => {
  expect(safeFlowError(status, { error: { code, message: "private" }, request_id: "flow-test-1" })).toMatchObject({ status, error: { code } });
});
it("mirrors strict native BMP text, byte bounds, phone and omitted email country rules", () => {
  for (const account of ["a+tag@example.test", "a b@example.test", "😀@example.test"]) expect(flowStartSchema.safeParse({ ...start, account }).success).toBe(false);
  expect(flowStartSchema.parse({ ...start, mode: "phone", account: "123", country_code: "82" })).toMatchObject({ country_code: "82" });
  expect(flowStartSchema.safeParse({ ...start, country_code: undefined }).success).toBe(false);
  for (const patch of [{ challenge_id: flow }, { challenge_generation: 1 }, { image_code: "1234" }, { challenge_id: flow, challenge_generation: true, image_code: "1234" }, { challenge_id: flow, challenge_generation: 2147483648, image_code: "1234" }, { challenge_id: flow, challenge_generation: 1, image_code: "😀" }]) expect(flowCodeSchema.safeParse({ ...reference, ...patch }).success).toBe(false);
  expect(flowCodeSchema.parse({ ...reference, challenge_id: null, challenge_generation: null, image_code: null })).toMatchObject(reference);
});
it("rejects noncanonical image Base64 and state extras", () => {
  const image = { challenge_id: flow, generation: 1, media_type: "image/png", image_base64: "AQ==" };
  for (const patch of [{ image_base64: "AR==" }, { image_base64: "AQ==\n" }, { media_type: "image/svg+xml" }, { generation: 0 }]) expect(flowViewSchema.safeParse({ ...view, state: "IMAGE_REQUIRED", image: { ...image, ...patch } }).success).toBe(false);
  expect(flowViewSchema.safeParse({ ...view, state: "IMAGE_REQUIRED", image }).success).toBe(true);
});
it("typed browser client keeps passwords in one protected request and has no automatic retry", async () => {
  vi.stubGlobal("window", { location: { origin } });
  const send = vi.fn<typeof fetch>().mockImplementation(async input => {
    const req = input as Request;
    expect(req.url).toBe(`${origin}/api/tvt/account-flows/register?tenant_id=${tenant}`);
    expect(req.credentials).toBe("same-origin"); expect(req.headers.get("X-CSRF-Token")).toBe("csrf");
    expect(await req.json()).toEqual(bodies.register);
    return new Response(JSON.stringify({ ...view, state: "COMPLETE", return_to_login: true }), { headers: { "X-Request-ID": requestId } });
  });
  vi.stubGlobal("fetch", send);
  const result = await accountFlowClient("csrf").register(tenant, { ...bodies.register, purpose: "register" }, new AbortController().signal);
  expect(result.return_to_login).toBe(true); expect(JSON.stringify(result)).not.toContain("private-password"); expect(send).toHaveBeenCalledTimes(1);
});
