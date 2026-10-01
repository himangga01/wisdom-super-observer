import "server-only";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { CSRF_COOKIE, SESSION_COOKIE, equalSecret, privateResponse, readAuthConfig } from "../auth";
import { consentInputSchema, consentSchema, preferencesInputSchema, preferencesSchema, publicBootstrap, publicMessages, tenantSchema } from "./api-client";

function privateJson(value: unknown, status: number) {
  const response = privateResponse(NextResponse.json(value, { status }));
  response.headers.set("Vary", "Cookie");
  return response;
}
function fail(status: number, requestId: string = randomUUID()) {
  return privateJson({ error: publicMessages[status] ?? publicMessages[503], request_id: requestId }, status);
}
async function boundedJson(response: Response, limit: number, signal: AbortSignal): Promise<unknown> {
  if (!response.body || Number(response.headers.get("content-length")) > limit) throw new Error("Invalid response");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  const abort = () => { void reader.cancel(); };
  signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error("Invalid response");
      chunks.push(value);
    }
  } finally { signal.removeEventListener("abort", abort); await reader.cancel(); }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}
function correlation(value: unknown): string | undefined {
  if (value && typeof value === "object" && "request_id" in value && typeof value.request_id === "string" && tenantSchema.safeParse(value.request_id).success) return value.request_id;
}
export async function proxyTvt(request: NextRequest, segments: string[], backendFetch: typeof fetch = fetch) {
  try {
    const tenant = request.nextUrl.searchParams.get("tenant_id");
    const route = segments[0];
    if (segments.length !== 1 || !["bootstrap", "consent", "preferences"].includes(route) || request.nextUrl.searchParams.size !== 1 || !tenantSchema.safeParse(tenant).success) return fail(404);
    const method = { bootstrap: "GET", consent: "POST", preferences: "PUT" }[route];
    if (request.method !== method) return fail(405);
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    if (!session) return fail(401);
    const config = readAuthConfig();
    const csrf = request.cookies.get(CSRF_COOKIE)?.value ?? "";
    let body: unknown;
    if (method !== "GET") {
      if (request.nextUrl.origin !== config.publicOrigin || request.headers.get("origin") !== config.publicOrigin || !equalSecret(csrf, request.headers.get("x-csrf-token") ?? "")) return fail(403);
      if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get("content-type") ?? "")) return fail(422);
      try {
        const value = await boundedJson(new Response(request.body), 4096, AbortSignal.any([request.signal, AbortSignal.timeout(10_000)]));
        body = route === "consent" ? consentInputSchema.parse(value) : preferencesInputSchema.parse(value);
      } catch { return fail(422); }
    }
    const controller = new AbortController();
    const signal = AbortSignal.any([request.signal, controller.signal]);
    const timer = setTimeout(() => controller.abort(), 10_000);
    try {
      const response = await backendFetch(`${config.apiOrigin}/api/v1/tvt/${route}?tenant_id=${tenant}`, {
        method, cache: "no-store", redirect: "error", signal,
        headers: { Cookie: `${SESSION_COOKIE}=${session}`, ...(method === "GET" ? {} : { Origin: config.publicOrigin, "X-CSRF-Token": csrf, "Content-Type": "application/json" }) },
        ...(method === "GET" ? {} : { body: JSON.stringify(body) }),
      });
      let data: unknown;
      try { data = await boundedJson(response, 65_536, signal); } catch { if (response.ok) return fail(503); }
      if (!response.ok) return fail([401, 403, 404, 409, 422, 503].includes(response.status) ? response.status : 503, correlation(data));
      if (response.status !== 200) return fail(503);
      const result = route === "bootstrap" ? publicBootstrap(data, tenant!) : route === "consent" ? consentSchema.parse(data) : preferencesSchema.parse(data);
      return privateJson(result, 200);
    } finally { clearTimeout(timer); }
  } catch { return fail(503); }
}
