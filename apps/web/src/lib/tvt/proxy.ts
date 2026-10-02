import "server-only";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { CSRF_COOKIE, SESSION_COOKIE, equalSecret, privateResponse, readAuthConfig } from "../auth";
import { consentInputSchema, consentSchema, preferencesInputSchema, preferencesSchema, publicBootstrap, publicMessages, tenantSchema } from "./api-client";
import { accountResponse, imageCheckSchema, loginSchema, refreshSchema, safeAccountError, selectionSchema, type AccountOperation, type AccountSelection } from "./account-api-client";

function privateJson(value: unknown, status: number, requestId: string) {
  const response = privateResponse(NextResponse.json(value, { status }));
  response.headers.set("Vary", "Cookie"); response.headers.set("X-Request-ID", requestId);
  return response;
}
function fail(status: number, requestId: string, account = false, code?: string) {
  const error = account ? safeAccountError(status, { error: { code: code ?? ({ 401: "authentication_required", 403: "csrf_rejected", 422: "validation_error", 503: "ACCOUNT_UNAVAILABLE", 504: "UNKNOWN_OUTCOME" } as Record<number, string>)[status] } }) : { status, error: publicMessages[status] ?? publicMessages[503] };
  if (account && (status === 404 || status === 405) && !code) return privateJson({ error: publicMessages[status], request_id: requestId }, status, requestId);
  return privateJson({ error: error.error, request_id: requestId }, error.status, requestId);
}
async function within<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  signal.throwIfAborted();
  let abort!: () => void;
  const cancellation = new Promise<never>((_resolve, reject) => { abort = () => reject(signal.reason ?? new Error("Cancelled")); signal.addEventListener("abort", abort, { once: true }); });
  try { return await Promise.race([promise, cancellation]); } finally { signal.removeEventListener("abort", abort); }
}
async function boundedBytes(response: Response, limit: number, signal: AbortSignal): Promise<Buffer> {
  const length = response.headers.get("content-length");
  if ((!response.body && limit !== 0) || (length !== null && (!/^\d+$/.test(length) || Number(length) > limit))) throw new Error("Invalid response");
  signal.throwIfAborted();
  if (!response.body) return Buffer.alloc(0);
  const reader = response.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  const abort = () => { void reader.cancel().catch(() => undefined); }; signal.addEventListener("abort", abort, { once: true });
  try {
    signal.throwIfAborted();
    while (true) {
      const { done, value } = await within(reader.read(), signal); signal.throwIfAborted(); if (done) break;
      size += value.byteLength; if (size > limit) throw new Error("Invalid response"); chunks.push(value);
    }
  } finally {
    signal.removeEventListener("abort", abort);
    // Cancellation hooks may never settle; cleanup must not extend the request budget.
    void reader.cancel().catch(() => undefined);
  }
  return Buffer.concat(chunks);
}
async function boundedJson(response: Response, limit: number, signal: AbortSignal): Promise<unknown> {
  return JSON.parse((await boundedBytes(response, limit, signal)).toString("utf8"));
}
function correlation(value: unknown): string | undefined {
  if (value && typeof value === "object" && "request_id" in value && tenantSchema.safeParse(value.request_id).success) return value.request_id as string;
}
function operation(segments: string[]): { method: string; account?: AccountOperation; id?: string; startup?: string } | undefined {
  if (segments.length === 1 && ["bootstrap", "consent", "preferences"].includes(segments[0])) return { method: { bootstrap: "GET", consent: "POST", preferences: "PUT" }[segments[0]]!, startup: segments[0] };
  const path = segments.join("/");
  if (path === "identities/login") return { method: "POST", account: "login" };
  if (path === "identities/challenges/image") return { method: "POST", account: "image" };
  if (path === "identities/challenges/image/check") return { method: "POST", account: "check" };
  if (segments.length === 3 && segments[0] === "identities" && tenantSchema.safeParse(segments[1]).success) {
    if (segments[2] === "me") return { method: "GET", account: "profile", id: segments[1] };
    if (segments[2] === "refresh" || segments[2] === "logout") return { method: "POST", account: segments[2], id: segments[1] };
  }
}
export async function proxyTvt(request: NextRequest, segments: string[], backendFetch: typeof fetch = fetch) {
  let requestId = randomUUID() as string;
  const isAccount = segments[0] === "identities";
  const controller = new AbortController(); const signal = AbortSignal.any([request.signal, controller.signal]);
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const tenant = request.nextUrl.searchParams.get("tenant_id"); const op = operation(segments);
    if (!op || request.nextUrl.pathname.endsWith("/") || /%|\\/.test(request.nextUrl.pathname) || request.nextUrl.searchParams.size !== 1 || !tenantSchema.safeParse(tenant).success) return fail(404, requestId, isAccount);
    if (request.method !== op.method) return fail(405, requestId, isAccount);
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    if (!session) return fail(401, requestId, isAccount);
    const config = readAuthConfig(); const csrf = request.cookies.get(CSRF_COOKIE)?.value ?? "";
    let body: unknown;
    if (op.method !== "GET") {
      if (request.nextUrl.origin !== config.publicOrigin || request.headers.get("origin") !== config.publicOrigin || !csrf || !equalSecret(csrf, request.headers.get("x-csrf-token") ?? "")) return fail(403, requestId, isAccount);
      if (op.account !== "logout") {
        if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get("content-type") ?? "")) return fail(422, requestId, isAccount);
        try {
          const value = await boundedJson(new Response(request.body, { headers: request.headers }), isAccount ? 32768 : 4096, signal);
          body = op.account ? { login: loginSchema, image: selectionSchema, check: imageCheckSchema, refresh: refreshSchema }[op.account as "login" | "image" | "check" | "refresh"].parse(value) : op.startup === "consent" ? consentInputSchema.parse(value) : preferencesInputSchema.parse(value);
        } catch { return fail(signal.aborted && isAccount ? 504 : 422, requestId, isAccount); }
      } else {
        // Next's Node adapter may expose an empty POST as a non-null stream.
        // Logout accepts exactly zero bytes, never an optional JSON payload.
        try { await boundedBytes(new Response(request.body, { headers: request.headers }), 0, signal); }
        catch { return fail(signal.aborted ? 504 : 422, requestId, true); }
      }
    }
    const response = await within(backendFetch(`${config.apiOrigin}/api/v1/tvt/${segments.join("/")}?tenant_id=${tenant}`, {
      method: op.method, cache: "no-store", redirect: "error", signal,
      headers: { Cookie: `${SESSION_COOKIE}=${session}`, ...(op.method === "GET" ? {} : { Origin: config.publicOrigin, "X-CSRF-Token": csrf, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }), signal);
    let data: unknown;
    try { data = await boundedJson(response, op.account === "image" && response.ok ? 131072 : 65536, signal); } catch { if (signal.aborted) throw new Error("Cancelled"); if (response.ok || isAccount) return fail(503, requestId, isAccount); }
    requestId = correlation(data) ?? requestId;
    if (!response.ok) {
      if (isAccount) { const safe = safeAccountError(response.status, data); return fail(safe.status, requestId, true, safe.error.code); }
      return fail([401, 403, 404, 409, 422, 503].includes(response.status) ? response.status : 503, requestId);
    }
    if (response.status !== 200) return fail(503, requestId, isAccount);
    const result = op.account ? accountResponse(op.account, data, op.id, op.account === "login" ? body as AccountSelection : undefined) : op.startup === "bootstrap" ? publicBootstrap(data, tenant!) : op.startup === "consent" ? consentSchema.parse(data) : preferencesSchema.parse(data);
    return privateJson(result, 200, requestId);
  } catch { return fail(signal.aborted && isAccount ? 504 : 503, requestId, isAccount); }
  finally { clearTimeout(timer); }
}
