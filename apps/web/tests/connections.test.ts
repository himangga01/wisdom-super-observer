import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxyConnection } from "../src/lib/connection-proxy";
import { publicConnection, parseConnectionBody } from "../src/lib/connections";

const tenant = "10000000-0000-4000-8000-000000000001";
const id = "30000000-0000-4000-8000-000000000001";
const config = {
  WSO_PUBLIC_ORIGIN: "https://app.example.com",
  WSO_OIDC_ISSUER: "https://id.example.com",
  WSO_OIDC_CLIENT_ID: "web",
  WSO_OIDC_CLIENT_SECRET: "secret",
  WSO_AUTH_EXCHANGE_KEY: "x".repeat(32),
  WSO_FLOW_ENCRYPTION_KEY: Buffer.alloc(32, 7).toString("base64url"),
  API_INTERNAL_ORIGIN: "http://127.0.0.1:8100",
};
const view = {
  id,
  tenant_id: tenant,
  kind: "TVT_ACCOUNT",
  alias: "입구",
  site: "본점",
  status: "NOT_VERIFIED",
  last_success: null,
  generation: 1,
  store_ids: [],
};
function request(
  method: string,
  body?: unknown,
  origin = config.WSO_PUBLIC_ORIGIN,
  csrf = "correct",
) {
  return new NextRequest(
    `${config.WSO_PUBLIC_ORIGIN}/api/connections?tenant_id=${tenant}`,
    {
      method,
      headers: {
        Origin: origin,
        Cookie: "__Host-wso-session=opaque; __Host-wso-csrf=correct",
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
}
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
describe("connection safety boundary", () => {
  it("allows zero stores and complete credential replacement but rejects partial, blank and unknown input", () => {
    expect(
      parseConnectionBody("create", {
        kind: "TVT_ACCOUNT",
        alias: "입구",
        site: "본점",
        username: "u",
        password: "p",
      }),
    ).toMatchObject({ store_ids: [] });
    expect(
      parseConnectionBody("patch", {
        expected_generation: 1,
        username: "u",
        password: "p",
      }),
    ).toMatchObject({ username: "u", password: "p" });
    for (const body of [
      { expected_generation: 1, username: "u" },
      { expected_generation: 0 },
      { expected_generation: 1, password: "" },
      { expected_generation: 1, alias: " " },
      { expected_generation: 1, secret_handle: "private" },
    ])
      expect(() => parseConnectionBody("patch", body)).toThrow();
  });
  it("projects public DTO fields and rejects unsupported status instead of implying online", () => {
    expect(
      publicConnection({
        ...view,
        username: "secret",
        password: "secret",
        ciphertext: "secret",
      }),
    ).toEqual(view);
    expect(() => publicConnection({ ...view, status: "ONLINE" })).toThrow();
  });
  it("rejects foreign Origin, mismatched CSRF and nonallowlisted paths before forwarding", async () => {
    Object.entries(config).forEach(([key, value]) => vi.stubEnv(key, value));
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(
      (
        await proxyConnection(
          request("DELETE", { expected_generation: 1 }, "https://evil.example"),
          [id],
        )
      ).status,
    ).toBe(403);
    expect(
      (
        await proxyConnection(
          request("DELETE", { expected_generation: 1 }, undefined, "wrong"),
          [id],
        )
      ).status,
    ).toBe(403);
    expect((await proxyConnection(request("GET"), ["..", "me"])).status).toBe(
      404,
    );
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("forwards fixed-origin cookie/CSRF generation writes without retry and sanitizes upstream data", async () => {
    Object.entries(config).forEach(([key, value]) => vi.stubEnv(key, value));
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ...view, password: "never-public" }), {
          status: 200,
        }),
      );
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyConnection(
      request("PATCH", { expected_generation: 1, alias: "변경" }),
      [id],
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(view);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(
      `http://127.0.0.1:8100/api/v1/connections/${id}?tenant_id=${tenant}`,
      expect.objectContaining({
        method: "PATCH",
        cache: "no-store",
        redirect: "error",
        body: '{"expected_generation":1,"alias":"변경"}',
        headers: expect.objectContaining({
          Cookie: "__Host-wso-session=opaque",
          Origin: config.WSO_PUBLIC_ORIGIN,
          "X-CSRF-Token": "correct",
        }),
      }),
    );
  });
  it("never forwards upstream validation details containing credentials", async () => {
    Object.entries(config).forEach(([key, value]) => vi.stubEnv(key, value));
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response('{"detail":"password=secret"}', { status: 422 }),
      );
    vi.stubGlobal("fetch", fetcher);
    const response = await proxyConnection(
      request("POST", {
        kind: "TVT_DEVICE",
        alias: "a",
        site: "s",
        username: "u",
        password: "p",
      }),
      [],
    );
    expect(response.status).toBe(422);
    expect(await response.text()).not.toContain("secret");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
