import type { Membership, Store } from "../lib/session";
import { ServiceShell } from "./service-shell";
const roleLabel: Record<string, string> = {
  OWNER: "소유자",
  MANAGER: "관리자",
  STAFF: "직원",
  owner: "소유자",
  manager: "관리자",
  staff: "직원",
};
export function StoresView({
  memberships,
  tenantId,
  stores,
  csrf,
}: {
  memberships: Membership[];
  tenantId?: string;
  stores: Store[];
  csrf: string;
}) {
  return (
    <ServiceShell
      csrf={csrf}
      tvtTenant={memberships.find((membership) => membership.tenant_id === tenantId)?.tenant_id ?? null}
      connectionTenant={
        memberships.find(
          (membership) =>
            membership.tenant_id === tenantId && membership.role === "OWNER",
        )?.tenant_id ??
        memberships.find((membership) => membership.role === "OWNER")?.tenant_id
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-[var(--wso-muted)]">
            매장 관리
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">
            내 매장
          </h1>
        </div>
        <span className="rounded-lg bg-[var(--wso-accent-soft)] px-3 py-2 text-xs font-medium text-[#226594]">
          선택 가능한 매장 {stores.length}개
        </span>
      </div>
      <p className="mt-3 text-[var(--wso-muted)]">관리할 매장을 선택하세요.</p>
      {memberships.length > 0 && (
        <form
          action="/stores"
          method="get"
          className="wso-card my-6 flex flex-wrap items-end gap-3 p-4"
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
              className="max-w-full rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2.5 text-sm"
            >
              {memberships.map((membership, index) => (
                <option key={membership.tenant_id} value={membership.tenant_id}>
                  조직 {index + 1} · {roleLabel[membership.role] ?? "멤버"}
                </option>
              ))}
            </select>
          </div>
          <button className="wso-button-primary" type="submit">
            조직 전환
          </button>
        </form>
      )}
      {stores.length === 0 ? (
        <div role="status" className="wso-card mt-6 p-8 text-center sm:p-12">
          <div
            aria-hidden="true"
            className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--wso-accent-soft)] text-xl text-[#226594]"
          >
            ▦
          </div>
          <p className="font-semibold">접근할 수 있는 매장이 없습니다.</p>
          <p className="mt-3 text-sm leading-6 text-[var(--wso-muted)]">
            관리자에게 매장 권한을 요청하세요.
          </p>
        </div>
      ) : (
        <ul className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {stores.map((store) => (
            <li key={store.id}>
              <a
                href={`/stores/${encodeURIComponent(store.id)}?tenant_id=${encodeURIComponent(store.tenant_id)}`}
                className="wso-card block p-5 transition hover:border-[var(--wso-accent)] hover:shadow-sm"
              >
                <div className="flex items-center justify-between">
                  <span
                    aria-hidden="true"
                    className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#F0F6FC] text-lg text-[#226594]"
                  >
                    ▦
                  </span>
                  <span className="rounded-full bg-[#EBF6EF] px-2.5 py-1 text-xs font-medium text-[var(--wso-success)]">
                    {store.active ? "운영 중" : "운영 중지"}
                  </span>
                </div>
                <span className="mt-5 block text-lg font-semibold">
                  {store.name}
                </span>
                <span className="mt-2 block text-xs text-[var(--wso-muted)]">
                  {store.timezone}
                </span>
                <span className="mt-6 flex items-center justify-between border-t border-[var(--wso-border)] pt-4 text-sm font-medium">
                  <span>매장 열기</span>
                  <span aria-hidden="true" className="text-[var(--wso-muted)]">
                    →
                  </span>
                </span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </ServiceShell>
  );
}
