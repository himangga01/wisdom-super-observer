"use client";
import { useEffect, useRef, useState } from "react";
import { AccountError, type AccountProfile, type AccountSelection } from "../../../lib/tvt/account-api-client";
import { useAccountSession } from "./SessionBoundary";
export function Profile({ tenantId, identityId, selection }: { tenantId: string; identityId: string; selection: AccountSelection }) {
  const session = useAccountSession(); const sessionRef = useRef(session);
  useEffect(() => { sessionRef.current = session; }, [session]);
  // PII lives only in this scoped component; no generic query or mutation cache.
  const [profile, setProfile] = useState<AccountProfile | null>(null); const [busy, setBusy] = useState(false); const [closed, setClosed] = useState(false); const [notice, setNotice] = useState(""); const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController(); active.current = controller;
    void sessionRef.current.execute(signal => sessionRef.current.api.profile(tenantId, identityId, { brand: selection.brand, region: selection.region }, AbortSignal.any([signal, controller.signal]))).then(value => { if (!controller.signal.aborted) setProfile(value); }).catch(async cause => { if (!controller.signal.aborted) await sessionRef.current.report(cause); });
    return () => { controller.abort(); active.current?.abort(); };
  }, [tenantId, identityId, selection.brand, selection.region]);
  async function mutate(logout: boolean) {
    if (busy || !profile) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setNotice("");
    try {
      if (logout) {
        await session.execute(signal => session.api.logout(tenantId, identityId, AbortSignal.any([signal, controller.signal])));
        controller.signal.throwIfAborted(); setProfile(null); setClosed(true); setNotice("TVT 계정을 로그아웃했습니다.");
        await session.requery();
      } else {
        await session.execute(signal => session.api.refresh(tenantId, identityId, profile.generation, selection, AbortSignal.any([signal, controller.signal])));
        const current = await session.execute(signal => session.api.profile(tenantId, identityId, selection, AbortSignal.any([signal, controller.signal])));
        controller.signal.throwIfAborted(); setProfile(current); setNotice("TVT 계정 상태를 갱신했습니다.");
      }
    } catch (cause) {
      if (controller.signal.aborted || (cause instanceof DOMException && cause.name === "AbortError")) return;
      setProfile(null); await session.report(cause);
      if (!controller.signal.aborted && cause instanceof AccountError && (cause.status === 409 || cause.code === "UNKNOWN_OUTCOME")) {
        // A current read resolves ambiguity. Renewal itself is never repeated.
        try { const current = await session.execute(signal => session.api.profile(tenantId, identityId, selection, signal)); if (!controller.signal.aborted) setProfile(current); } catch (error) { await session.report(error); }
      }
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }
  if (closed) return <p role="status">{notice}</p>;
  if (!profile) return <p role="status">TVT 계정 정보를 확인합니다.</p>;
  return <section className="wso-card p-6" aria-labelledby="tvt-profile-title" aria-busy={busy}><h2 id="tvt-profile-title" className="text-lg font-semibold">현재 TVT 계정</h2>
    <dl className="mt-4 space-y-3 break-words">{[["계정 ID", profile.identity_id], ["계정 유형", profile.profile.account_type], ["계정 상태", profile.state], ["세션 버전", profile.generation], ["사용자 이름", profile.profile.user_name], ["별명", profile.profile.nickname], ["이메일", profile.profile.email], ["전화번호", profile.profile.mobile], ["주소", profile.profile.address], ["프로필 이미지", profile.profile.avatar_available ? "등록되어 있습니다." : "등록되어 있지 않습니다."]].map(([label, value]) => <div key={label}><dt className="text-xs text-[var(--wso-muted)]">{label}</dt><dd className="mt-1">{value === "" ? "—" : value}</dd></div>)}</dl>
    {notice && <p role="status" className="mt-4">{notice}</p>}
    <div className="mt-5 flex flex-wrap gap-3"><button className="wso-button-secondary" disabled={busy || profile.state === "CLOSED"} onClick={() => void mutate(false)}>TVT 세션 갱신</button><button className="wso-button-secondary" disabled={busy} onClick={() => void mutate(true)}>TVT 로그아웃</button></div>
  </section>;
}
