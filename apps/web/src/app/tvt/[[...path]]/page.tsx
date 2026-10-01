import { cookies } from "next/headers";
import { SESSION_COOKIE } from "../../../lib/auth";
import { csrfToken, requireSession } from "../../../lib/session";
import { tenantSchema } from "../../../lib/tvt/api-client";
import { ServiceShell } from "../../../components/service-shell";
import { SessionRefresh } from "../../../components/session-refresh";
import { TvtShell } from "../../../features/tvt/shell/TvtShell";
import "../../../styles/tvt.css";
export const dynamic = "force-dynamic";
export default async function TvtPage({ params, searchParams }: {
  params: Promise<{ path?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const path = "/tvt" + ((await params).path?.length ? "/" + (await params).path!.join("/") : "");
  if (!(await cookies()).get(SESSION_COOKIE)?.value) return <ServiceShell active="tvt"><TvtShell path={path} /></ServiceShell>;
  const me = await requireSession();
  const selection = await searchParams;
  const requested = selection.tenant_id;
  const exact = Object.keys(selection).every(key => key === "tenant_id") && typeof requested === "string" && tenantSchema.safeParse(requested).success;
  const admitted = exact && me.memberships.some(item => item.tenant_id === requested);
  const csrf = await csrfToken();
  const tenantId = admitted ? requested : undefined;
  return <ServiceShell csrf={csrf} active="tvt" connectionTenant={tenantId}>
    <SessionRefresh expiresAt={me.expires_at} />
    <TvtShell userId={me.user_id} tenantId={tenantId} csrf={csrf} path={path} invalidSelection={Object.keys(selection).length > 0 && !admitted} />
  </ServiceShell>;
}
