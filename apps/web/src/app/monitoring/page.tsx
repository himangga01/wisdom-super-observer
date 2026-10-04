/* eslint-disable @next/next/no-html-link-for-pages -- Full navigation refetches owner grants and avoids personalized Router Cache. */
import { notFound } from "next/navigation";
import {
  apiRequest,
  csrfToken,
  requireSession,
  ServiceError,
  type Store,
} from "../../lib/session";
import { publicConnection } from "../../lib/connections";
import { ServiceShell } from "../../components/service-shell";
import { SessionRefresh } from "../../components/session-refresh";
import { LiveWall } from "../../features/monitoring/live-wall";
export const dynamic = "force-dynamic";
export default async function MonitoringPage({
  searchParams,
}: {
  searchParams: Promise<{ tenant_id?: string }>;
}) {
  const me = await requireSession();
  const requested = (await searchParams).tenant_id;
  const tenantId =
    requested ??
    me.memberships.find((membership) => membership.role === "OWNER")
      ?.tenant_id ??
    me.memberships[0]?.tenant_id;
  const membership = me.memberships.find((item) => item.tenant_id === tenantId);
  if (requested && !membership) notFound();
  const csrf = await csrfToken();
  if (!membership || membership.role !== "OWNER")
    return (
      <ServiceShell csrf={csrf} active="monitoring">
        <SessionRefresh expiresAt={me.expires_at} />
        <div className="wso-card p-6">
          <h1 className="text-2xl font-semibold">소유자 권한이 필요합니다</h1>
          <p className="mt-3 text-[var(--wso-muted)]">
            연결 관리는 조직 소유자만 사용할 수 있습니다. 조직 소유자에게
            문의하세요.
          </p>
          <a href="/stores" className="wso-button-secondary mt-5">
            내 매장으로 이동
          </a>
        </div>
      </ServiceShell>
    );
  const owner = membership.tenant_id;
  const [connections, storeResponse] = await Promise.all([
    apiRequest(`/connections?tenant_id=${encodeURIComponent(owner)}`),
    apiRequest(`/stores?tenant_id=${encodeURIComponent(owner)}`),
  ]);
  if (connections.status === 404 || storeResponse.status === 404) notFound();
  if (!connections.ok) throw new ServiceError(connections.status);
  if (!storeResponse.ok) throw new ServiceError(storeResponse.status);
  const items = ((await connections.json()) as { items: unknown[] }).items.map(
    publicConnection,
  );
  if (items.some((item) => item.tenant_id !== owner))
    throw new ServiceError(503);
  const stores = ((await storeResponse.json()) as { items: Store[] }).items;
  // Only TVT recorders and active stores can contribute saved channels; the wall pairs them.
  const recorders = items.filter(
    (item) => item.kind === "TVT_DEVICE" && item.status !== "DISCONNECTED",
  );
  return (
    <ServiceShell csrf={csrf} active="monitoring" connectionTenant={owner}>
      <SessionRefresh expiresAt={me.expires_at} />
      <LiveWall
        tenantId={owner}
        csrf={csrf}
        stores={stores.filter(
          (store) => store.active && store.tenant_id === owner,
        )}
        connections={recorders}
      />
    </ServiceShell>
  );
}
