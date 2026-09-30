import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { CSRF_COOKIE, SESSION_COOKIE, readAuthConfig } from "./auth";
export type Membership = { tenant_id: string; role: string };
export type Me = { user_id: string; memberships: Membership[]; expires_at: string };
export type Store = { id: string; tenant_id: string; name: string; timezone: string; active: boolean };
export class ServiceError extends Error { constructor(public status: number) { super("Service unavailable"); } }
export async function apiRequest(path: string): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!session) redirect("/?expired=1");
  try {
    const response = await fetch(`${readAuthConfig().apiOrigin}/api/v1${path}`, { headers: { Cookie: `${SESSION_COOKIE}=${session}` }, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (response.status === 401) redirect("/?expired=1");
    return response;
  } catch (error) {
    if (error instanceof Error && "digest" in error) throw error;
    throw new ServiceError(503);
  }
}
export async function requireSession(): Promise<Me> {
  const response = await apiRequest("/me");
  if (!response.ok) throw new ServiceError(response.status);
  const me = await response.json() as Me;
  if (!Number.isFinite(Date.parse(me.expires_at)) || Date.parse(me.expires_at) <= Date.now()) redirect("/?expired=1");
  return me;
}
export async function csrfToken() { return (await cookies()).get(CSRF_COOKIE)?.value ?? ""; }
