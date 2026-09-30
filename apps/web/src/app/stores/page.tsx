import { notFound } from "next/navigation";
import { apiRequest, csrfToken, requireSession, ServiceError, type Store } from "../../lib/session";
import { StoresView } from "../../components/stores-view";
import { SessionRefresh } from "../../components/session-refresh";
export const dynamic = "force-dynamic";
export default async function StoresPage({ searchParams }: { searchParams: Promise<{ tenant_id?: string }> }) {
  const me = await requireSession();
  const requested = (await searchParams).tenant_id;
  const tenantId = requested ?? me.memberships[0]?.tenant_id;
  if (requested && !me.memberships.some(m => m.tenant_id === requested)) notFound();
  let stores: Store[] = [];
  if (tenantId) {
    const response = await apiRequest(`/stores?tenant_id=${encodeURIComponent(tenantId)}`);
    if (response.status === 404) notFound();
    if (!response.ok) throw new ServiceError(response.status);
    stores = (await response.json() as { items: Store[] }).items;
  }
  return <><SessionRefresh expiresAt={me.expires_at} /><StoresView memberships={me.memberships} tenantId={tenantId} stores={stores} csrf={await csrfToken()} /></>;
}
