import { describe, expect, it, vi, afterEach } from "vitest";
import { NextRequest } from "next/server";
import { encryptFlow, decryptFlow, readAuthConfig, safeReturnTo, authErrorResponse } from "../src/lib/auth";
import { GET as logoutGet, POST as logoutPost } from "../src/app/api/auth/logout/route";

const settings = {
  WSO_PUBLIC_ORIGIN: "https://app.example.com",
  WSO_OIDC_ISSUER: "https://id.example.com",
  WSO_OIDC_CLIENT_ID: "web", WSO_OIDC_CLIENT_SECRET: "private-secret",
  WSO_AUTH_EXCHANGE_KEY: "private-exchange",
  WSO_FLOW_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"),
  API_INTERNAL_ORIGIN: "http://127.0.0.1:8100",
};
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
describe("authentication boundary", () => {
  it("offers a safe accessible retry for failed authentication", async () => {
    const response = authErrorResponse(400);
    expect(response.status).toBe(400);
    expect(response.headers.get("cache-control")).toContain("no-store");
    const html = await response.text();
    expect(html).toContain("<h1");
    expect(html).toContain('href="/api/auth/login"');
  });
  it("requires HTTPS origins and independent 32-byte flow key", () => {
    expect(readAuthConfig(settings).publicOrigin).toBe(settings.WSO_PUBLIC_ORIGIN);
    expect(() => readAuthConfig({ ...settings, WSO_PUBLIC_ORIGIN: "http://localhost:3000" })).toThrow();
    expect(() => readAuthConfig({ ...settings, API_INTERNAL_ORIGIN: "http://10.0.0.1" })).toThrow();
    expect(() => readAuthConfig({ ...settings, WSO_FLOW_ENCRYPTION_KEY: "short" })).toThrow();
    expect(() => readAuthConfig({ ...settings, WSO_OIDC_ISSUER: "http://localhost:9000" })).toThrow();
  });
  it("allows only local store destinations", () => {
    expect(safeReturnTo("/stores?tenant_id=abc")).toBe("/stores?tenant_id=abc");
    for (const value of ["//evil.com", "https://evil.com", "/api/auth/logout", "/stores/../../api/auth/logout", "/stores\\evil"]) {
      expect(safeReturnTo(value)).toBe("/stores");
    }
  });
  it("encrypts short-lived flow state and rejects tampering/expiry", () => {
    const key = Buffer.alloc(32, 7);
    const flow = { state: "random-state", nonce: "random-nonce", verifier: "private-verifier", returnTo: "/stores", expires: Date.now() + 60_000 };
    const encrypted = encryptFlow(flow, key);
    expect(encrypted).not.toContain(flow.verifier);
    expect(decryptFlow(encrypted, key)).toEqual(flow);
    expect(() => decryptFlow(encrypted.slice(0, -2) + "zz", key)).toThrow();
    expect(() => decryptFlow(encrypted, Buffer.alloc(32, 8))).toThrow();
    expect(() => decryptFlow(encryptFlow({ ...flow, expires: Date.now() - 1 }, key), key)).toThrow();
  });
  it("GET logout does not mutate cookies or revoke sessions", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const response = await logoutGet();
    expect(response.status).toBe(405);
    expect(response.headers.get("set-cookie")).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("rejects logout with foreign Origin or mismatched CSRF before API call", async () => {
    Object.entries(settings).forEach(([key, value]) => vi.stubEnv(key, value));
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const [origin, token] of [["https://evil.com", "correct"], [settings.WSO_PUBLIC_ORIGIN, "wrong"]]) {
      const request = new NextRequest(`${settings.WSO_PUBLIC_ORIGIN}/api/auth/logout`, { method: "POST", headers: { Origin: origin, Cookie: "__Host-wso-session=opaque; __Host-wso-csrf=correct", "Content-Type": "application/x-www-form-urlencoded" }, body: `csrf_token=${token}` });
      expect((await logoutPost(request)).status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
});
