import createClient from "openapi-fetch";
import { z } from "zod";
import type { components, operations, paths } from "../../../../../packages/contracts/generated/tvt";

export type Bootstrap = components["schemas"]["StartupBootstrap"];
export type Consent = components["schemas"]["StartupConsent"];
export type ConsentInput = operations["tvtConsent"]["requestBody"]["content"]["application/json"];
export type Preferences = operations["tvtPreferences"]["requestBody"]["content"]["application/json"];
export const tenantSchema = z.string().uuid();
const version = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/);
const locale = z.string().max(35).regex(/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/);
const timezone = z.string().min(1).max(64).refine(value => {
  try { new Intl.DateTimeFormat("en", { timeZone: value }); return true; } catch { return false; }
});
const policy = (kind: "ServiceTerms" | "PrivacyStatement") => z.object({
  source_reference: z.enum(["agreement/ServiceTerms_en.html", "agreement/PrivacyStatement_en.html", "agreement/ServiceTerms_zh-Hans.html", "agreement/PrivacyStatement_zh-Hans.html"]).refine(value => value.startsWith(`agreement/${kind}_`)),
  url: z.string().max(2048).refine(value => { try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password && !url.search && !url.hash && !/[\s\u0000-\u001f]/.test(value); } catch { return false; } }),
});
export const consentSchema = z.object({
  version, status: z.enum(["pending", "accepted", "declined"]),
  decided_at: z.string().datetime({ offset: true }).nullable(), terms: policy("ServiceTerms"), privacy: policy("PrivacyStatement"),
}).refine(value => value.status === "pending" ? value.decided_at === null : value.decided_at !== null);
export const preferencesSchema = z.object({ locale, timezone });
export const consentInputSchema = z.object({ version, decision: z.enum(["accepted", "declined"]) }).strict();
export const preferencesInputSchema = preferencesSchema.strict();
const bootstrapSchema = z.object({
  selected_tenant_id: tenantSchema, profile_id: version, brand: z.literal("SuperLivePlus"), region: version,
  locale, timezone, supported_locales: z.array(locale).min(1).max(50), consent: consentSchema,
  identity: z.object({ state: z.enum(["unlinked", "linked"]), accounts: z.array(z.object({ id: tenantSchema, brand: z.string().min(1).max(64), region: z.string().min(1).max(64) })).max(200) }).refine(value => value.state === "linked" ? value.accounts.length > 0 : value.accounts.length === 0),
  menu: z.array(z.union([
    z.object({ id: z.literal("local-settings"), label: z.literal("Settings"), path: z.literal("/tvt/settings") }),
    z.object({ id: z.literal("local-account"), label: z.literal("Account"), path: z.literal("/tvt/account") }),
  ])).max(2).refine(value => new Set(value.map(entry => entry.id)).size === value.length),
}).refine(value => value.supported_locales.includes(value.locale));
export function publicBootstrap(value: unknown, tenant: string): Bootstrap {
  const result = bootstrapSchema.parse(value);
  if (result.selected_tenant_id !== tenant) throw new Error("Invalid scope");
  return result;
}
export const publicMessages: Record<number, { code: string; message: string }> = {
  401: { code: "authentication_required", message: "로그인 시간이 만료되었습니다. 다시 로그인하세요." },
  403: { code: "forbidden", message: "요청을 확인할 수 없습니다. 페이지를 다시 열어주세요." },
  404: { code: "not_found", message: "이 페이지를 사용할 수 없습니다." },
  405: { code: "method_not_allowed", message: "지원하지 않는 요청입니다." },
  409: { code: "consent_version_changed", message: "약관이 변경되었습니다. 최신 내용을 확인하세요." },
  422: { code: "validation_error", message: "언어와 시간대 또는 동의 정보를 확인하세요." },
  503: { code: "startup_unavailable", message: "서비스 정보를 불러올 수 없습니다. 잠시 후 다시 시도하세요." },
};
export class TvtError extends Error {
  constructor(public status: number) { super((publicMessages[status] ?? publicMessages[503]).message); }
}
export function startupClient(csrf: string) {
  const browserClient = () => createClient<paths>({
    baseUrl: window.location.origin, credentials: "same-origin", cache: "no-store", redirect: "error",
    fetch: async request => {
      const url = new URL(request.url);
      url.pathname = url.pathname.replace(/^\/api\/v1\/tvt\//, "/api/tvt/");
      return fetch(new Request(url.toString(), {
        method: request.method, headers: request.headers, signal: request.signal,
        credentials: "same-origin", cache: "no-store", redirect: "error",
        ...(request.method === "GET" ? {} : { body: await request.text() }),
      }));
    },
  });
  const checked = <T>(response: Response, data: T | undefined): T => {
    if (!response.ok || data === undefined) throw new TvtError(response.status);
    return data;
  };
  return {
    async bootstrap(tenant: string, signal: AbortSignal) {
      const result = await browserClient().GET("/api/v1/tvt/bootstrap", { params: { query: { tenant_id: tenant } }, signal });
      try { return publicBootstrap(checked(result.response, result.data), tenant); } catch (error) { if (error instanceof TvtError) throw error; throw new TvtError(503); }
    },
    async consent(tenant: string, body: ConsentInput, signal: AbortSignal): Promise<Consent> {
      const result = await browserClient().POST("/api/v1/tvt/consent", { params: { query: { tenant_id: tenant } }, body, headers: { "X-CSRF-Token": csrf }, signal });
      return consentSchema.parse(checked(result.response, result.data));
    },
    async preferences(tenant: string, body: Preferences, signal: AbortSignal): Promise<Preferences> {
      const result = await browserClient().PUT("/api/v1/tvt/preferences", { params: { query: { tenant_id: tenant } }, body, headers: { "X-CSRF-Token": csrf }, signal });
      return preferencesSchema.parse(checked(result.response, result.data));
    },
  };
}
