import createClient from "openapi-fetch";
import { z } from "zod";
import type { components, paths } from "../../../../../packages/contracts/generated/tvt";
import { tenantSchema } from "./api-client";

type PublishedAccountLogin = components["schemas"]["AccountLogin"];
export type AccountLogin = Omit<PublishedAccountLogin, "mode" | "country_code"> & ({ mode: "email"; country_code?: null } | { mode: "phone"; country_code: string });
export type AccountSelection = components["schemas"]["AccountSelection"];
export type AccountIdentity = components["schemas"]["AccountIdentity"];
export type AccountProfile = components["schemas"]["AccountProfileView"];
export type ImageChallenge = components["schemas"]["ImageChallengeView"];
const scope = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/);
const supportedText = (max: number) => z.string().min(1).max(max).refine(value => !/[\u0000\uD800-\uDFFF]/u.test(value) && Array.from(value).every(character => character.codePointAt(0)! <= 0xffff));
export const selectionSchema = z.object({ region: scope, brand: scope }).strict();
const loginFields = selectionSchema.extend({
  secret: supportedText(4096),
  challenge_id: tenantSchema.nullable().optional(), image_code: supportedText(256).nullable().optional(), second_code: supportedText(256).nullable().optional(),
});
export const loginSchema = z.discriminatedUnion("mode", [
  loginFields.extend({ mode: z.literal("email"), account: supportedText(512).regex(/^[^\s@]+@[^\s@]+\.[^\s@]+$/), country_code: z.null().optional() }).strict(),
  loginFields.extend({ mode: z.literal("phone"), account: z.string().min(1).max(32).regex(/^[0-9]+$/), country_code: z.string().min(1).max(4).regex(/^[0-9]+$/) }).strict(),
]).refine(value => Boolean(value.challenge_id) === Boolean(value.image_code));
export const imageCheckSchema = selectionSchema.extend({ challenge_id: tenantSchema, image_code: supportedText(256) }).strict();
export const refreshSchema = z.object({ kind: z.literal("USER").default("USER"), expected_generation: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER), reason: z.enum(["manual", "upstream_expired", "reconnect"]).default("manual") }).strict();
export const identitySchema = z.object({ identity_id: tenantSchema, region: scope, brand: scope, state: z.enum(["NEW", "AUTHENTICATING", "READY", "REFRESHING", "EXPIRED", "CLOSED"]), generation: z.number().int().min(1).max(Number.MAX_SAFE_INTEGER), request_id: tenantSchema });
const publicText = z.string().max(4096);
export const profileSchema = identitySchema.extend({ profile: z.object({ account_type: z.number().int().min(-2147483648).max(2147483647), user_name: publicText, nickname: publicText, email: publicText, mobile: publicText, address: publicText, no_password: z.boolean(), avatar_available: z.boolean(), avatar_url: z.null() }) });
export const challengeSchema = z.object({ challenge_id: tenantSchema, media_type: z.enum(["image/jpeg", "image/png"]), image_base64: z.string().min(4).max(90000).regex(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/), expires_in_seconds: z.literal(120), request_id: tenantSchema });
export const imageCheckedSchema = z.object({ checked: z.literal(true), request_id: tenantSchema });
export const logoutSchema = z.object({ identity_id: tenantSchema, state: z.literal("CLOSED"), upstream_outcome: z.enum(["confirmed", "unknown", "not_attempted"]), request_id: tenantSchema });

// Exact status/code pairs keep web authorization distinct from a TVT token.
export const accountErrors: Record<string, { status: number | number[]; message: string }> = {
  unauthenticated: { status: 401, message: "웹 로그인 시간이 만료되었습니다. 다시 로그인하세요." },
  authentication_required: { status: 401, message: "웹 로그인이 필요합니다." },
  principal_not_provisioned: { status: 403, message: "웹 계정의 조직 접근 권한을 확인할 수 없습니다." },
  csrf_rejected: { status: 403, message: "요청을 확인할 수 없습니다. 페이지를 다시 열어주세요." },
  forbidden: { status: 403, message: "선택한 조직에 접근할 수 없습니다." },
  AUTH_REQUIRED: { status: 401, message: "TVT 계정에 다시 로그인하세요." },
  TOKEN_EXPIRED: { status: 401, message: "TVT 계정의 로그인 시간이 만료되었습니다." },
  ACCOUNT_DENIED: { status: [404, 409], message: "선택한 TVT 계정의 현재 상태를 확인할 수 없습니다." },
  CHALLENGE_EXPIRED: { status: 409, message: "이미지 확인 시간이 만료되었습니다. 새 이미지를 요청하세요." },
  GENERATION_CONFLICT: { status: 409, message: "계정 상태가 변경되었습니다. 현재 상태를 확인합니다." },
  RENEWAL_OUTCOME_UNKNOWN: { status: 409, message: "갱신 결과를 확인할 수 없습니다. 다시 갱신하지 말고 현재 상태를 확인하세요." },
  consent_required: { status: 409, message: "현재 약관에 동의한 뒤 계정을 이용하세요." },
  consent_version_changed: { status: 409, message: "약관이 변경되었습니다. 최신 내용을 확인하세요." },
  validation_error: { status: 422, message: "계정과 비밀번호, 확인 코드를 확인하세요." },
  ACCOUNT_INPUT_INVALID: { status: 422, message: "계정 입력 형식을 확인하세요." },
  UNKNOWN_OUTCOME: { status: 504, message: "요청 결과를 확인할 수 없습니다. 자동으로 다시 제출하지 않습니다. 현재 계정 상태를 확인하세요." },
  ACCOUNT_DEADLINE_EXCEEDED: { status: 504, message: "계정 요청 시간이 초과되었습니다. 현재 상태를 확인하세요." },
  ACCOUNT_UNAVAILABLE: { status: 503, message: "계정 서비스를 사용할 수 없습니다. 잠시 후 다시 확인하세요." },
  auth_unavailable: { status: 503, message: "웹 로그인 권한을 확인할 수 없습니다. 잠시 후 다시 확인하세요." },
  not_found: { status: 404, message: "선택한 조직 또는 TVT 계정을 사용할 수 없습니다." },
  ACCOUNT_UPSTREAM_REJECTED: { status: 502, message: "계정 또는 비밀번호, 지역과 확인 코드를 확인하세요." },
  ACCOUNT_SCOPE_INVALID: { status: 502, message: "선택한 지역에서 계정을 사용할 수 없습니다." },
  ACCOUNT_PROTOCOL_INVALID: { status: 502, message: "계정 응답을 확인할 수 없습니다." },
  ACCOUNT_TRANSPORT_FAILED: { status: 502, message: "계정 서비스에 연결할 수 없습니다." },
  ACCOUNT_CANCELLED: { status: 502, message: "계정 요청이 취소되었습니다." },
  ACCOUNT_QUARANTINED: { status: 502, message: "계정 서비스를 사용할 수 없습니다." },
  ACCOUNT_DC_PENDING: { status: 502, message: "계정 서비스의 지역 정보를 확인할 수 없습니다." },
};
export function safeAccountError(status: number, value: unknown) {
  const envelope = z.object({ error: z.object({ code: z.string().max(64) }), request_id: tenantSchema.optional() }).safeParse(value);
  const code = envelope.success ? envelope.data.error.code : "ACCOUNT_UNAVAILABLE";
  const known = accountErrors[code];
  if (!envelope.success || !known || !(Array.isArray(known.status) ? known.status.includes(status) : known.status === status)) return { status: 503, error: { code: "ACCOUNT_UNAVAILABLE", message: accountErrors.ACCOUNT_UNAVAILABLE.message } };
  return { status, error: { code, message: known.message } };
}
export class AccountError extends Error {
  constructor(public status: number, public code: string) { super(accountErrors[code]?.message ?? accountErrors.ACCOUNT_UNAVAILABLE.message); }
}
export type AccountOperation = "login" | "image" | "check" | "profile" | "refresh" | "logout";
export function accountResponse(operation: AccountOperation, value: unknown, identityId?: string, selection?: AccountSelection) {
  const result = { login: identitySchema, image: challengeSchema, check: imageCheckedSchema, profile: profileSchema, refresh: identitySchema, logout: logoutSchema }[operation].parse(value);
  if ("identity_id" in result && identityId && result.identity_id !== identityId) throw new Error("Invalid account scope");
  if ("region" in result && selection && (result.region !== selection.region || result.brand !== selection.brand)) throw new Error("Invalid account selection");
  return result;
}
export function accountClient(csrf: string) {
  // Created only when a browser action runs, never at SSR/module evaluation.
  const client = () => createClient<paths>({ baseUrl: window.location.origin, credentials: "same-origin", cache: "no-store", redirect: "error", fetch: async request => {
    const url = new URL(request.url); url.pathname = url.pathname.replace(/^\/api\/v1\/tvt\//, "/api/tvt/");
    return fetch(new Request(url.toString(), { method: request.method, headers: request.headers, signal: request.signal, credentials: "same-origin", cache: "no-store", redirect: "error", ...(request.body === null ? {} : { body: await request.text() }) }));
  } });
  const checked = (response: Response, data: unknown, error: unknown, signal: AbortSignal) => {
    signal.throwIfAborted();
    if (!response.ok || data === undefined) { const safe = safeAccountError(response.status, error); throw new AccountError(safe.status, safe.error.code); }
    return data;
  };
  const headers = { "X-CSRF-Token": csrf };
  return {
    async login(tenant: string, body: AccountLogin, signal: AbortSignal): Promise<AccountIdentity> {
      const result = await client().POST("/api/v1/tvt/identities/login", { params: { query: { tenant_id: tenant } }, body: loginSchema.parse(body), headers, signal });
      return accountResponse("login", checked(result.response, result.data, result.error, signal), undefined, body) as AccountIdentity;
    },
    async image(tenant: string, body: AccountSelection, signal: AbortSignal): Promise<ImageChallenge> {
      const result = await client().POST("/api/v1/tvt/identities/challenges/image", { params: { query: { tenant_id: tenant } }, body: selectionSchema.parse(body), headers, signal });
      return challengeSchema.parse(checked(result.response, result.data, result.error, signal));
    },
    async check(tenant: string, body: components["schemas"]["ImageCheckRequest"], signal: AbortSignal) {
      const result = await client().POST("/api/v1/tvt/identities/challenges/image/check", { params: { query: { tenant_id: tenant } }, body: imageCheckSchema.parse(body), headers, signal });
      return imageCheckedSchema.parse(checked(result.response, result.data, result.error, signal));
    },
    async profile(tenant: string, id: string, selection: AccountSelection, signal: AbortSignal): Promise<AccountProfile> {
      const result = await client().GET("/api/v1/tvt/identities/{identity_id}/me", { params: { query: { tenant_id: tenant }, path: { identity_id: id } }, signal });
      return accountResponse("profile", checked(result.response, result.data, result.error, signal), id, selection) as AccountProfile;
    },
    async refresh(tenant: string, id: string, generation: number, selection: AccountSelection, signal: AbortSignal): Promise<AccountIdentity> {
      const result = await client().POST("/api/v1/tvt/identities/{identity_id}/refresh", { params: { query: { tenant_id: tenant }, path: { identity_id: id } }, body: refreshSchema.parse({ kind: "USER", expected_generation: generation, reason: "manual" }), headers, signal });
      return accountResponse("refresh", checked(result.response, result.data, result.error, signal), id, selection) as AccountIdentity;
    },
    async logout(tenant: string, id: string, signal: AbortSignal) {
      const result = await client().POST("/api/v1/tvt/identities/{identity_id}/logout", { params: { query: { tenant_id: tenant }, path: { identity_id: id } }, headers, signal });
      return logoutSchema.parse(accountResponse("logout", checked(result.response, result.data, result.error, signal), id));
    },
  };
}
export type AccountApi = ReturnType<typeof accountClient>;
