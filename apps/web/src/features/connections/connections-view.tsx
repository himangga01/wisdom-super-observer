/* eslint-disable @next/next/no-location-assign-relative-destination -- Full navigation discards personalized client state on session expiry. */
"use client";
import { useEffect, useRef, useState } from "react";
import type { Store } from "../../lib/session";
import {
  connectionMessage,
  kindLabel,
  publicConnection,
  type ConnectionView,
} from "../../lib/connections";
import { ConnectionForm } from "./connection-form";
import { LocalDeviceInventory } from "./local-device-inventory";
export function ConnectionsView({
  tenantId,
  initial,
  stores,
  csrf,
}: {
  tenantId: string;
  initial: ConnectionView[];
  stores: Store[];
  csrf: string;
}) {
  const [items, setItems] = useState(initial);
  const [editing, setEditing] = useState<ConnectionView | "new" | null>(null);
  const [confirmation, setConfirmation] = useState<{
    item: ConnectionView;
    action: "delete" | "disconnect";
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(0);
  const locked = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const errorMessage = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) errorMessage.current?.focus();
  }, [error]);
  const endpoint = (id?: string, action?: string) =>
    `/api/connections${id ? "/" + id : ""}${action ? "/" + action : ""}?tenant_id=${encodeURIComponent(tenantId)}`;
  async function refresh() {
    const response = await fetch(endpoint(), {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (response.status === 401) {
      window.location.assign("/?expired=1");
      return null;
    }
    if (!response.ok) throw new Error(connectionMessage(response.status));
    const current = ((await response.json()) as { items: unknown[] }).items.map(
      publicConnection,
    );
    setItems(current);
    return current;
  }
  async function mutate(
    method: string,
    body: unknown,
    id?: string,
    action?: string,
  ) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch(endpoint(id, action), {
        method,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(body),
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
      if (response.status === 401) {
        window.location.assign("/?expired=1");
        return;
      }
      if (response.status === 409) {
        setConfirmation(null);
        // Reload sanitized state once; never retry a write automatically.
        const current = await refresh();
        setEditing(
          id ? (current?.find((item) => item.id === id) ?? null) : "new",
        );
        setRevision((value) => value + 1);
        setError(connectionMessage(409));
        return;
      }
      if (!response.ok) {
        setError(connectionMessage(response.status));
        return;
      }
      setEditing(null);
      setConfirmation(null);
      setRevision((value) => value + 1);
      setNotice(
        method === "DELETE"
          ? "연결을 삭제했습니다."
          : action
            ? "연결을 해제했습니다."
            : "연결 정보를 저장했습니다.",
      );
      await refresh();
      heading.current?.focus();
    } catch {
      setError(connectionMessage(503));
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  return (
    <section aria-busy={busy}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-medium text-[var(--wso-muted)]">
            계정 및 기기 관리
          </p>
          <h1
            ref={heading}
            tabIndex={-1}
            className="mt-2 text-2xl font-semibold tracking-tight"
          >
            연결 관리
          </h1>
          <p className="mt-3 leading-6 text-[var(--wso-muted)]">
            TVT·TYCO 계정과 기기 정보를 관리하세요.
          </p>
        </div>
        <button
          onClick={() => {
            setEditing("new");
            setConfirmation(null);
            setError("");
          }}
          disabled={busy}
          className="wso-button-primary"
        >
          새 연결
        </button>
      </div>
      {error && (
        <div
          role="alert"
          ref={errorMessage}
          tabIndex={-1}
          className="mt-5 rounded-lg border border-[#E6B7B7] bg-[#FFF7F7] p-4 text-[#8C2424]"
        >
          {error}
        </div>
      )}
      {notice && (
        <p role="status" className="mt-4 text-[var(--wso-success)]">
          {notice}
        </p>
      )}
      {editing && (
        <ConnectionForm
          key={`${editing === "new" ? "new" : editing.id}-${revision}`}
          connection={editing === "new" ? undefined : editing}
          stores={stores}
          busy={busy}
          onCancel={() => setEditing(null)}
          onSubmit={(body) =>
            mutate(
              editing === "new" ? "POST" : "PATCH",
              body,
              editing === "new" ? undefined : editing.id,
            )
          }
        />
      )}
      {confirmation && (
        <section
          role="alertdialog"
          aria-labelledby="confirmation-title"
          aria-describedby="confirmation-description"
          className="wso-card mt-6 border-[#E6B7B7] p-5"
        >
          <h2 id="confirmation-title" className="text-lg font-semibold">
            {confirmation.action === "delete"
              ? "연결을 삭제할까요?"
              : "연결을 해제할까요?"}
          </h2>
          <p
            id="confirmation-description"
            className="mt-3 leading-6 text-[var(--wso-muted)]"
          >
            {confirmation.item.alias}의 저장된 계정 정보가 제거됩니다.{" "}
            {confirmation.action === "delete"
              ? "연결 목록에서도 삭제되며 다시 사용하려면 새로 등록해야 합니다."
              : "다시 사용하려면 계정 정보를 교체해 저장해야 합니다."}
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              autoFocus
              disabled={busy}
              className="wso-button-secondary"
              onClick={() => setConfirmation(null)}
            >
              취소
            </button>
            <button
              disabled={busy}
              className="wso-button-primary"
              onClick={() =>
                mutate(
                  confirmation.action === "delete" ? "DELETE" : "POST",
                  { expected_generation: confirmation.item.generation },
                  confirmation.item.id,
                  confirmation.action === "disconnect"
                    ? "disconnect"
                    : undefined,
                )
              }
            >
              {confirmation.action === "delete" ? "삭제 확인" : "해제 확인"}
            </button>
          </div>
        </section>
      )}
      {items.length === 0 ? (
        <div className="wso-card mt-6 p-8 text-center sm:p-12">
          <div
            aria-hidden="true"
            className="mx-auto mb-5 grid h-12 w-12 place-items-center rounded-xl bg-[var(--wso-accent-soft)] text-xl text-[#226594]"
          >
            ⇄
          </div>
          <p className="font-semibold">등록된 연결이 없습니다.</p>
          <p className="mt-3 leading-6 text-[var(--wso-muted)]">
            새 연결에서 계정 또는 기기를 등록하세요. 매장은 나중에 연결할 수
            있습니다.
          </p>
        </div>
      ) : (
        <ul className="mt-6 grid min-w-0 gap-4 lg:grid-cols-2">
          {items.map((item) => (
            <li key={item.id} className="wso-card min-w-0 p-5">
              <div className="flex flex-wrap justify-between gap-3">
                <span className="text-xs font-medium text-[var(--wso-muted)]">
                  {kindLabel[item.kind]}
                </span>
                <span className="rounded-full bg-[#F0F2F5] px-3 py-1 text-xs font-medium">
                  {item.status === "DISCONNECTED" ? "해제됨" : "미확인"}
                </span>
              </div>
              <h2 className="mt-4 break-words text-lg font-semibold">
                {item.alias}
              </h2>
              <p className="mt-2 break-words text-[var(--wso-muted)]">
                {item.site}
              </p>
              <dl className="mt-5 space-y-3 text-sm">
                <div>
                  <dt className="text-xs text-[var(--wso-muted)]">
                    연결된 매장
                  </dt>
                  <dd className="mt-1 break-words">
                    {item.store_ids.length
                      ? item.store_ids
                          .map(
                            (id) =>
                              stores.find((store) => store.id === id)?.name ??
                              "접근할 수 없는 매장",
                          )
                          .join(" · ")
                      : "연결된 매장 없음"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-[var(--wso-muted)]">
                    최근 연결 성공
                  </dt>
                  <dd className="mt-1">
                    {item.last_success
                      ? new Date(item.last_success).toLocaleString("ko-KR")
                      : "아직 확인되지 않았습니다."}
                  </dd>
                </div>
              </dl>
              {item.kind === "TVT_DEVICE" && <LocalDeviceInventory tenantId={tenantId} connection={item} stores={stores} csrf={csrf} disabled={busy} />}
              <div className="mt-5 flex flex-wrap gap-2 border-t border-[var(--wso-border)] pt-4">
                <button
                  disabled={busy}
                  className="wso-button-secondary"
                  onClick={() => {
                    setEditing(item);
                    setConfirmation(null);
                    setError("");
                  }}
                >
                  수정
                </button>
                {item.status !== "DISCONNECTED" && (
                  <button
                    disabled={busy}
                    className="wso-button-secondary"
                    onClick={() => {
                      setConfirmation({ item, action: "disconnect" });
                      setEditing(null);
                    }}
                  >
                    연결 해제
                  </button>
                )}
                <button
                  disabled={busy}
                  className="wso-button-secondary"
                  onClick={() => {
                    setConfirmation({ item, action: "delete" });
                    setEditing(null);
                  }}
                >
                  삭제
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
