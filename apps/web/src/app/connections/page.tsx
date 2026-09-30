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
import { ConnectionsView } from "../../features/connections/connections-view";
export const dynamic = "force-dynamic";
export default async function ConnectionsPage({
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
      <ServiceShell csrf={csrf} active="connections">
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
  const [connections, storeResponse] = await Promise.all([
    apiRequest(`/connections?tenant_id=${tenantId}`),
    apiRequest(`/stores?tenant_id=${tenantId}`),
  ]);
  if (connections.status === 404 || storeResponse.status === 404) notFound();
  if (!connections.ok) throw new ServiceError(connections.status);
  if (!storeResponse.ok) throw new ServiceError(storeResponse.status);
  const items = ((await connections.json()) as { items: unknown[] }).items.map(
    publicConnection,
  );
  if (items.some((item) => item.tenant_id !== tenantId))
    throw new ServiceError(503);
  const stores = ((await storeResponse.json()) as { items: Store[] }).items;
  return (
    <ServiceShell csrf={csrf} active="connections" connectionTenant={tenantId}>
      <SessionRefresh expiresAt={me.expires_at} />
      <form
        action="/connections"
        method="get"
        className="wso-card mb-6 flex flex-wrap items-end gap-3 p-4"
      >
        <div className="min-w-0">
          <label
            htmlFor="tenant"
            className="mb-2 block text-xs font-medium text-[var(--wso-muted)]"
          >
            조직 선택
          </label>
          <select
            id="tenant"
            name="tenant_id"
            defaultValue={tenantId}
            className="max-w-full rounded-lg border border-[var(--wso-border)] px-3 py-2.5"
          >
            {me.memberships
              .filter((item) => item.role === "OWNER")
              .map((item, index) => (
                <option key={item.tenant_id} value={item.tenant_id}>
                  조직 {index + 1} · 소유자
                </option>
              ))}
          </select>
        </div>
        <button className="wso-button-primary" type="submit">
          조직 전환
        </button>
      </form>
      <ConnectionsView
        tenantId={tenantId!}
        initial={items}
        stores={stores}
        csrf={csrf}
      />
    </ServiceShell>
  );
}
