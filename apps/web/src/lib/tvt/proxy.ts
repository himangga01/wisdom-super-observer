import "server-only";
import { randomUUID } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { CSRF_COOKIE, SESSION_COOKIE, equalSecret, privateResponse, readAuthConfig } from "../auth";
import { consentInputSchema, consentSchema, preferencesInputSchema, preferencesSchema, publicBootstrap, publicMessages, tenantSchema } from "./api-client";
import { accountResponse, imageCheckSchema, loginSchema, refreshSchema, safeAccountError, selectionSchema, type AccountOperation, type AccountSelection } from "./account-api-client";
import { flowInputSchemas, flowRequestIdSchema, flowResponse, safeFlowError, type FlowOperation } from "./flow-api-client";

import { directoryInput, directoryInputSchemas, directoryJson, directoryRequestIdSchema, directoryResponse, safeDirectoryError, type DirectoryOperation, type DirectoryRequest } from "./directory-api-client";

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
async function boundedJson(response: Response, limit: number, signal: AbortSignal, directory = false): Promise<unknown> {
  const bytes = await boundedBytes(response, limit, signal);
  return directory ? directoryJson(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) : JSON.parse(bytes.toString("utf8"));
}
function correlation(value: unknown): string | undefined {
  if (value && typeof value === "object" && "request_id" in value && tenantSchema.safeParse(value.request_id).success) return value.request_id as string;
}
function operation(segments: string[]): { method: string; account?: AccountOperation; flow?: FlowOperation; directory?: DirectoryOperation; id?: string; startup?: string } | undefined {
  if (segments.length === 1 && ["bootstrap", "consent", "preferences"].includes(segments[0])) return { method: { bootstrap: "GET", consent: "POST", preferences: "PUT" }[segments[0]]!, startup: segments[0] };
  const path = segments.join("/");
  if (segments.length === 2 && segments[0] === "directory" && Object.hasOwn(directoryInputSchemas, segments[1])) return { method: "POST", directory: segments[1] as DirectoryOperation };
  if (segments.length === 2 && segments[0] === "account-flows" && Object.hasOwn(flowInputSchemas, segments[1])) return { method: "POST", flow: segments[1] as FlowOperation };
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
  const isDirectory = segments[0] === "directory";
  const denied = (status: number, id: string, account = false, code?: string) => {
    if (!isDirectory) return fail(status, id, account, code);
    if (status === 405) return privateJson({ error: { code: "http_error", message: "Directory request failed" }, request_id: id }, status, id);
    const fixed = code ?? ({401:"authentication_required",403:"csrf_rejected",404:"not_found",422:"validation_error",503:"ACCOUNT_UNAVAILABLE",504:"ACCOUNT_DEADLINE_EXCEEDED"} as Record<number,string>)[status];
    const safe = safeDirectoryError(status,{error:{code:fixed},request_id:id});
    return privateJson({error:safe.error,request_id:id},safe.status,id);
  };
  const isAccount = segments[0] === "identities" || segments[0] === "account-flows";
  const controller = new AbortController(); const signal = AbortSignal.any([request.signal, controller.signal]);
  const timer = setTimeout(() => controller.abort(), 10_000);
  try {
    const tenant = request.nextUrl.searchParams.get("tenant_id"); const op = operation(segments);
    if (!op || request.nextUrl.pathname.endsWith("/") || /%|\\/.test(request.nextUrl.pathname) || request.nextUrl.searchParams.size !== 1 || !tenantSchema.safeParse(tenant).success) return denied(404, requestId, isAccount);
    if (request.method !== op.method) return denied(405, requestId, isAccount);
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    if (!session) return denied(401, requestId, isAccount);
    const config = readAuthConfig(); const csrf = request.cookies.get(CSRF_COOKIE)?.value ?? "";
    let body: unknown;
    if (op.method !== "GET") {
      if (request.nextUrl.origin !== config.publicOrigin || request.headers.get("origin") !== config.publicOrigin || !csrf || !equalSecret(csrf, request.headers.get("x-csrf-token") ?? "")) return denied(403, requestId, isAccount);
      if (op.account !== "logout") {
        if (!/^application\/json(?:\s*;\s*charset=utf-8)?$/i.test(request.headers.get("content-type") ?? "")) return denied(422, requestId, isAccount);
        try {
          const value = await boundedJson(new Response(request.body, { headers: request.headers }), op.directory ? 65536 : isAccount ? 32768 : 4096, signal, !!op.directory);
          body = op.directory ? directoryInput(op.directory, value) : op.flow ? flowInputSchemas[op.flow].parse(value) : op.account ? { login: loginSchema, image: selectionSchema, check: imageCheckSchema, refresh: refreshSchema }[op.account as "login" | "image" | "check" | "refresh"].parse(value) : op.startup === "consent" ? consentInputSchema.parse(value) : preferencesInputSchema.parse(value);
        } catch { return denied(signal.aborted && (isAccount || isDirectory) ? 504 : 422, requestId, isAccount); }
      } else {
        // Next's Node adapter may expose an empty POST as a non-null stream.
        // Logout accepts exactly zero bytes, never an optional JSON payload.
        try { await boundedBytes(new Response(request.body, { headers: request.headers }), 0, signal); }
        catch { return denied(signal.aborted ? 504 : 422, requestId, true); }
      }
    }
    const response = await within(backendFetch(`${config.apiOrigin}/api/v1/tvt/${segments.join("/")}?tenant_id=${tenant}`, {
      method: op.method, cache: "no-store", redirect: "error", signal,
      headers: { Cookie: `${SESSION_COOKIE}=${session}`, ...(op.method === "GET" ? {} : { Origin: config.publicOrigin, "X-CSRF-Token": csrf, ...(body === undefined ? {} : { "Content-Type": "application/json" }) }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }), signal);
    let data: unknown;
    try { data = await boundedJson(response, op.directory ? 1048576 : response.ok && (op.account === "image" || op.flow === "image" || op.flow === "issue-code") ? 131072 : 65536, signal, !!op.directory); } catch { if (signal.aborted) throw new Error("Cancelled"); if (response.ok || isAccount || isDirectory) return denied(503, requestId, isAccount); }
    if (op.directory) {
      if (!data || typeof data !== "object" || !("request_id" in data) || !directoryRequestIdSchema.safeParse(data.request_id).success || response.headers.get("X-Request-ID") !== data.request_id) return denied(503, requestId);
      requestId = data.request_id as string;
    }
    if (op.flow && data && typeof data === "object" && "request_id" in data && flowRequestIdSchema.safeParse(data.request_id).success) requestId = data.request_id as string;
    else if (!op.directory) requestId = correlation(data) ?? requestId;
    if (op.flow && response.headers.has("X-Request-ID") && response.headers.get("X-Request-ID") !== requestId) return denied(503, requestId, true);
    if (!response.ok) {
      if (op.directory) { const safe = safeDirectoryError(response.status, data); return privateJson({ error: safe.error, request_id: requestId }, safe.status, requestId); }
      if (op.flow) { const safe = safeFlowError(response.status, data); return privateJson({ error: safe.error, request_id: requestId }, safe.status, requestId); }
      if (isAccount) { const safe = safeAccountError(response.status, data); return denied(safe.status, requestId, true, safe.error.code); }
      return denied([401, 403, 404, 409, 422, 503].includes(response.status) ? response.status : 503, requestId);
    }
    if (response.status !== 200) return denied(503, requestId, isAccount);
    const result = op.directory ? directoryResponse(data, body as DirectoryRequest, response.headers.get("X-Request-ID") ?? undefined) : op.flow ? flowResponse(data, body as { region: string; brand: string; purpose: "register" | "recover"; flow_id?: string }, response.headers.get("X-Request-ID") ?? undefined) : op.account ? accountResponse(op.account, data, op.id, op.account === "login" ? body as AccountSelection : undefined) : op.startup === "bootstrap" ? publicBootstrap(data, tenant!) : op.startup === "consent" ? consentSchema.parse(data) : preferencesSchema.parse(data);
    if (op.directory) signal.throwIfAborted();
    return privateJson(result, 200, requestId);
  } catch { return denied(signal.aborted && (isAccount || isDirectory) ? 504 : 503, requestId, isAccount); }
  finally { clearTimeout(timer); }
}
