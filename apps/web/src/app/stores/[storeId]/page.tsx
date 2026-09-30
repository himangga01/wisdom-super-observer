import { notFound } from "next/navigation";
import { apiRequest, csrfToken, requireSession, ServiceError, type Store } from "../../../lib/session";
import { ServiceShell } from "../../../components/service-shell";
import { SessionRefresh } from "../../../components/session-refresh";
export const dynamic = "force-dynamic";
export default async function StorePage({ params, searchParams }: { params: Promise<{ storeId: string }>; searchParams: Promise<{ tenant_id?: string }> }) {
  const me = await requireSession();
  const tenantId = (await searchParams).tenant_id;
  const { storeId } = await params;
  if (!tenantId || !me.memberships.some(m => m.tenant_id === tenantId) || !/^[0-9a-f-]{36}$/i.test(storeId)) notFound();
  const response = await apiRequest(`/stores/${encodeURIComponent(storeId)}?tenant_id=${encodeURIComponent(tenantId)}`);
  if (response.status === 404) notFound();
  if (!response.ok) throw new ServiceError(response.status);
  const store = await response.json() as Store;
  return <><SessionRefresh expiresAt={me.expires_at} /><ServiceShell csrf={await csrfToken()}><a href={`/stores?tenant_id=${encodeURIComponent(tenantId)}`} className="text-sm text-[var(--wso-muted)]">← 매장 목록</a><p className="mt-6 text-xs font-medium text-[var(--wso-success)]">{store.active ? "운영 중" : "운영 중지"}</p><h1 className="mt-2 text-2xl font-semibold">{store.name}</h1><p className="mt-3 text-[var(--wso-muted)]">매장 작업 공간</p><dl className="wso-card mt-6 p-6"><dt className="text-xs text-[var(--wso-muted)]">시간대</dt><dd className="mt-2 font-medium">{store.timezone}</dd></dl></ServiceShell></>;
}
