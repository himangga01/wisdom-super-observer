import { notFound } from "next/navigation";
import {
  apiRequest,
  csrfToken,
  requireSession,
  ServiceError,
  type Store,
} from "../../../lib/session";
import { publicConnection, uuid } from "../../../lib/connections";
import { ServiceShell } from "../../../components/service-shell";
import { SessionRefresh } from "../../../components/session-refresh";
import { ConnectionsView } from "../../../features/connections/connections-view";
export const dynamic = "force-dynamic";
export default async function ConnectionPage({
  params,
  searchParams,
}: {
  params: Promise<{ connectionId: string }>;
  searchParams: Promise<{ tenant_id?: string }>;
}) {
  const me = await requireSession();
  const tenant = (await searchParams).tenant_id;
  const id = (await params).connectionId;
  const membership = me.memberships.find((item) => item.tenant_id === tenant);
  if (!uuid.safeParse(id).success || !membership) notFound();
  if (membership.role !== "OWNER")
    return (
      <ServiceShell csrf={await csrfToken()}>
        <SessionRefresh expiresAt={me.expires_at} />
        <h1 className="text-2xl font-semibold">소유자 권한이 필요합니다</h1>
        <p className="mt-3">연결 관리는 조직 소유자만 사용할 수 있습니다.</p>
      </ServiceShell>
    );
  const response = await apiRequest(`/connections/${id}?tenant_id=${tenant}`);
  if (response.status === 404) notFound();
  if (!response.ok) throw new ServiceError(response.status);
  const connection = publicConnection(await response.json());
  if (connection.tenant_id !== tenant) notFound();
  const stores = await apiRequest(`/stores?tenant_id=${tenant}`);
  if (!stores.ok) throw new ServiceError(stores.status);
  const csrf = await csrfToken();
  return (
    <ServiceShell csrf={csrf} active="connections" connectionTenant={tenant}>
      <SessionRefresh expiresAt={me.expires_at} />
      <ConnectionsView
        tenantId={tenant!}
        initial={[connection]}
        stores={((await stores.json()) as { items: Store[] }).items}
        csrf={csrf}
      />
    </ServiceShell>
  );
}
