import createClient from "openapi-fetch";
import { z } from "zod";
import type { components, paths } from "../../../../../packages/contracts/generated/tvt";
import { safeAccountError } from "./account-api-client";

export type FlowOperation = "start" | "state" | "existence" | "image" | "issue-code" | "register" | "recover" | "cancel";
type Schemas = components["schemas"];
export type AccountFlowStart = Omit<Schemas["AccountFlowStart"], "mode" | "country_code"> & ({ mode: "email"; country_code?: never } | { mode: "phone"; country_code: string });
export type AccountFlowReference = Schemas["AccountFlowReference"];
export type AccountDynamicCodeRequest = Schemas["AccountDynamicCodeRequest"];
export type AccountRegistrationSubmit = Schemas["AccountRegistrationSubmit"];
export type AccountRecoverySubmit = Schemas["AccountRecoverySubmit"];
export type AccountFlowView = Schemas["AccountFlowView"];
type FlowInput = AccountFlowStart | AccountFlowReference | AccountDynamicCodeRequest | AccountRegistrationSubmit | AccountRecoverySubmit;

// Python UUID accepts any UUID version, including nil, and canonicalizes case.
export const flowUuidSchema = z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i).transform(value => value.toLowerCase());
export const flowRequestIdSchema = z.string().min(1).max(128).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/);
const scope = z.string().min(1).max(64).regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/);
const nativeText = (max: number) => z.string().min(1).max(max).refine(value => !/[\u0000\uD800-\uDFFF]/u.test(value) && Array.from(value).every(c => c.codePointAt(0)! <= 0xffff) && new TextEncoder().encode(value).length <= 4096);
const selection = z.object({ region: scope, brand: scope, purpose: z.enum(["register", "recover"]) }).strict();
export const flowStartSchema = z.discriminatedUnion("mode", [
  selection.extend({ mode: z.literal("email"), account: nativeText(512).regex(/^[-_.a-zA-Z0-9]+@[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+$/) }).strict(),
  selection.extend({ mode: z.literal("phone"), account: z.string().regex(/^[0-9]{1,32}$/), country_code: z.string().regex(/^[0-9]{1,4}$/) }).strict(),
]);
export const flowReferenceSchema = selection.extend({ flow_id: flowUuidSchema }).strict();
const generation = z.number().int().min(1).max(2147483647);
export const flowCodeSchema = flowReferenceSchema.extend({ challenge_id: flowUuidSchema.nullable().optional(), challenge_generation: generation.nullable().optional(), image_code: nativeText(256).nullable().optional() }).strict().refine(value => {
  const present = [value.challenge_id, value.challenge_generation, value.image_code].map(value => value != null);
  return present.every(Boolean) || present.every(value => !value);
});
const finalCode = nativeText(6).refine(value => value.length === 6);
export const flowRegisterSchema = flowReferenceSchema.extend({ purpose: z.literal("register"), password: nativeText(4096), dynamic_code: finalCode }).strict();
export const flowRecoverSchema = flowReferenceSchema.extend({ purpose: z.literal("recover"), new_password: nativeText(4096), dynamic_code: finalCode }).strict();
export const flowInputSchemas = { start: flowStartSchema, state: flowReferenceSchema, existence: flowReferenceSchema, image: flowReferenceSchema, "issue-code": flowCodeSchema, register: flowRegisterSchema, recover: flowRecoverSchema, cancel: flowReferenceSchema } as const;
const flowErrorCodeSchema = z.enum(["ACCOUNT_INPUT_INVALID", "ACCOUNT_SCOPE_INVALID", "ACCOUNT_PROTOCOL_INVALID", "ACCOUNT_TRANSPORT_FAILED", "ACCOUNT_DEADLINE_EXCEEDED", "ACCOUNT_CANCELLED", "ACCOUNT_UNAVAILABLE", "ACCOUNT_QUARANTINED", "ACCOUNT_UPSTREAM_REJECTED", "ACCOUNT_DC_PENDING", "FLOW_CLOSED", "FLOW_EXPIRED", "FLOW_CONSUMED", "FLOW_KEY_MISSING", "FLOW_PURPOSE_INVALID", "FLOW_IMAGE_MISSING", "FLOW_RATE_LIMITED"]);
const flowImageSchema = z.object({ challenge_id: flowUuidSchema, generation, media_type: z.enum(["image/jpeg", "image/png"]), image_base64: z.string().min(4).max(90000).refine(value => {
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) return false;
  try { const bytes = atob(value); return bytes.length >= 1 && bytes.length <= 65536 && btoa(bytes) === value; } catch { return false; }
}) }).strict();
export const flowViewSchema = flowReferenceSchema.extend({
  request_id: flowRequestIdSchema, state: z.enum(["CREATED", "EXISTENCE", "IMAGE_AVAILABLE", "IMAGE_REQUIRED", "IMAGE_REJECTED", "CODE_SENT", "COMPLETE", "FAILED", "UNKNOWN_OUTCOME", "CLOSED", "EXPIRED"]),
  exists: z.boolean().nullable().optional(), image: flowImageSchema.nullable().optional(), error_code: flowErrorCodeSchema.nullable().optional(),
  expires_in_seconds: z.number().int().min(1).max(86400).nullable().optional(), resend_wait_seconds: z.number().int().min(0).max(3600).nullable().optional(),
  return_to_login: z.boolean().default(false), automatic_retry_permitted: z.literal(false).default(false),
}).strict().refine(value =>
  (value.state === "COMPLETE") === value.return_to_login &&
  (value.state === "EXISTENCE") === (value.exists != null) &&
  ["IMAGE_AVAILABLE", "IMAGE_REQUIRED", "IMAGE_REJECTED"].includes(value.state) === (value.image != null) &&
  (value.state !== "IMAGE_REJECTED" || value.purpose === "register") &&
  (value.error_code == null || ["FAILED", "UNKNOWN_OUTCOME", "CLOSED", "EXPIRED"].includes(value.state))
);
export function flowResponse(value: unknown, input: Pick<FlowInput, "region" | "brand" | "purpose"> & { flow_id?: string }, requestId?: string): AccountFlowView {
  const result = flowViewSchema.parse(value);
  if (result.region !== input.region || result.brand !== input.brand || result.purpose !== input.purpose || (input.flow_id !== undefined && result.flow_id !== flowUuidSchema.parse(input.flow_id)) || (requestId !== undefined && result.request_id !== requestId)) throw new Error("Invalid flow response");
  return result;
}
const flowFailures: Record<string, string> = {
  FLOW_CLOSED: "계정 요청이 닫혔습니다.", FLOW_EXPIRED: "계정 확인 시간이 만료되었습니다.", FLOW_CONSUMED: "이미 처리된 계정 요청입니다.", FLOW_KEY_MISSING: "계정 확인을 다시 시작하세요.", FLOW_PURPOSE_INVALID: "계정 요청 목적을 확인하세요.", FLOW_IMAGE_MISSING: "새 확인 이미지를 요청하세요.", FLOW_RATE_LIMITED: "잠시 후 확인 코드를 요청하세요.",
};
const flowFailureStatuses: Record<string, number> = {
  ACCOUNT_SCOPE_INVALID: 422, ACCOUNT_CANCELLED: 409, ACCOUNT_QUARANTINED: 409,
  FLOW_CLOSED: 409, FLOW_EXPIRED: 409, FLOW_CONSUMED: 409, FLOW_KEY_MISSING: 409,
  FLOW_PURPOSE_INVALID: 422, FLOW_IMAGE_MISSING: 409, FLOW_RATE_LIMITED: 429,
  CAPABILITY_UNSUPPORTED: 409, SESSION_BUSY: 409, FORBIDDEN: 403, RATE_LIMITED: 429, UPSTREAM_TIMEOUT: 504,
};
export function safeFlowError(status: number, value: unknown) {
  const envelope = z.object({ error: z.object({ code: z.string().max(64), message: z.string().max(512).optional() }).strict(), request_id: flowRequestIdSchema }).strict().safeParse(value);
  if (!envelope.success) return safeAccountError(503, { error: { code: "ACCOUNT_UNAVAILABLE" } });
  const code = envelope.data.error.code;
  if (Object.hasOwn(flowFailureStatuses, code)) {
    if (status !== flowFailureStatuses[code]) return safeAccountError(503, { error: { code: "ACCOUNT_UNAVAILABLE" } });
    return { status, error: { code, message: flowFailures[code] ?? "계정 요청의 현재 상태를 확인하세요." } };
  }
  // Use the established safe messages, with the flow request-id grammar checked above.
  return safeAccountError(status, { error: { code } });
}
export class AccountFlowError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}
export function accountFlowClient(csrf: string) {
  const client = () => createClient<paths>({ baseUrl: window.location.origin, credentials: "same-origin", cache: "no-store", redirect: "error", fetch: request => {
    const url = new URL(request.url); url.pathname = url.pathname.replace(/^\/api\/v1\/tvt\//, "/api/tvt/");
    return fetch(new Request(url, request));
  } });
  async function send(operation: FlowOperation, tenant: string, input: FlowInput, signal: AbortSignal): Promise<AccountFlowView> {
    const body = flowInputSchemas[operation].parse(input);
    const result = await client().POST(`/api/v1/tvt/account-flows/${operation}`, { params: { query: { tenant_id: flowUuidSchema.parse(tenant) } }, body, headers: { "X-CSRF-Token": csrf }, signal });
    signal.throwIfAborted();
    if (!result.response.ok || result.data === undefined) {
      const failure = safeFlowError(result.response.status, result.error);
      throw new AccountFlowError(failure.status, failure.error.code, failure.error.message);
    }
    if (result.response.status !== 200) throw new AccountFlowError(503, "ACCOUNT_UNAVAILABLE", "계정 응답을 확인할 수 없습니다.");
    return flowResponse(result.data, body, result.response.headers.get("X-Request-ID") ?? undefined);
  }
  return {
    start: (tenant: string, body: AccountFlowStart, signal: AbortSignal) => send("start", tenant, body, signal),
    state: (tenant: string, body: AccountFlowReference, signal: AbortSignal) => send("state", tenant, body, signal),
    existence: (tenant: string, body: AccountFlowReference, signal: AbortSignal) => send("existence", tenant, body, signal),
    image: (tenant: string, body: AccountFlowReference, signal: AbortSignal) => send("image", tenant, body, signal),
    issueCode: (tenant: string, body: AccountDynamicCodeRequest, signal: AbortSignal) => send("issue-code", tenant, body, signal),
    register: (tenant: string, body: AccountRegistrationSubmit, signal: AbortSignal) => send("register", tenant, body, signal),
    recover: (tenant: string, body: AccountRecoverySubmit, signal: AbortSignal) => send("recover", tenant, body, signal),
    cancel: (tenant: string, body: AccountFlowReference, signal: AbortSignal) => send("cancel", tenant, body, signal),
  };
}
export type AccountFlowApi = ReturnType<typeof accountFlowClient>;
