/* eslint-disable @next/next/no-html-link-for-pages -- Full navigation rechecks current authorization. */
"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { startupClient, TvtError, publicMessages, type Bootstrap, type ConsentInput, type Preferences } from "../../../lib/tvt/api-client";
import { TvtQueryProvider, startupKey } from "../../../lib/tvt/query-provider";
import { ConsentGate } from "./ConsentGate";
import { FeatureMenu } from "./FeatureMenu";
import { DeepLinkResolver } from "./DeepLinkResolver";

export type TvtShellProps = { userId?: string; tenantId?: string; csrf?: string; path?: string; invalidSelection?: boolean };
export function TvtShell(props: TvtShellProps) {
  if (!props.userId) return <div className="wso-card p-6"><h1 className="text-2xl font-semibold">SuperLivePlus</h1><p className="mt-3">로그인하여 서비스를 이용하세요.</p><a className="wso-button-primary mt-5" href="/api/auth/login">로그인</a></div>;
  if (!props.tenantId || props.invalidSelection) return <div className="wso-card p-6"><h1 className="text-2xl font-semibold">SuperLivePlus</h1><p role={props.invalidSelection ? "alert" : "status"} className="mt-3">{props.invalidSelection ? "선택한 조직을 사용할 수 없습니다." : "내 매장에서 조직을 선택하세요."}</p><a className="wso-button-secondary mt-5" href="/stores">내 매장으로 이동</a></div>;
  return <TvtQueryProvider key={`${props.userId}:${props.tenantId}`}><Startup {...props} userId={props.userId} tenantId={props.tenantId} /></TvtQueryProvider>;
}
function Settings({ bootstrap, busy, onSave }: { bootstrap: Bootstrap; busy: boolean; onSave: (body: Preferences) => void }) {
  const [locale, setLocale] = useState(bootstrap.locale);
  const [timezone, setTimezone] = useState(bootstrap.timezone);
  return <section className="wso-card p-6" aria-labelledby="settings-title"><h2 id="settings-title" className="text-lg font-semibold">설정</h2>
    <form className="mt-5 space-y-4" onSubmit={event => { event.preventDefault(); onSave({ locale, timezone }); }} aria-busy={busy}>
      <div><label htmlFor="tvt-locale" className="mb-2 block font-medium">언어</label><select className="tvt-input" id="tvt-locale" value={locale} onChange={event => setLocale(event.target.value)} disabled={busy}>{bootstrap.supported_locales.map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      <div><label htmlFor="tvt-timezone" className="mb-2 block font-medium">시간대</label><input className="tvt-input" id="tvt-timezone" value={timezone} onChange={event => setTimezone(event.target.value)} maxLength={64} required disabled={busy} aria-describedby="tvt-timezone-help" /><p id="tvt-timezone-help" className="mt-2 text-xs text-[var(--wso-muted)]">IANA 시간대 이름을 입력하세요. 예: Asia/Seoul</p></div>
      <button className="wso-button-primary" disabled={busy} type="submit">설정 저장</button>
    </form>
  </section>;
}
function Startup({ userId, tenantId, csrf = "", path = "/tvt" }: TvtShellProps & { userId: string; tenantId: string }) {
  const queryClient = useQueryClient();
  const [api] = useState(() => startupClient(csrf));
  const [lostAuthorization, setLostAuthorization] = useState<401 | 403 | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const activeWrite = useRef<AbortController | null>(null);
  const locked = useRef(false);
  const alert = useRef<HTMLParagraphElement>(null);
  const key = startupKey({ userId, tenantId });
  const loseAccess = (status: 401 | 403) => {
    setLostAuthorization(status);
    activeWrite.current?.abort();
    void queryClient.cancelQueries();
    queryClient.clear();
  };
  const load = async (signal: AbortSignal) => {
    try { return await api.bootstrap(tenantId, signal); } catch (cause) {
      if (cause instanceof TvtError && (cause.status === 401 || cause.status === 403)) loseAccess(cause.status);
      throw cause;
    }
  };
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => load(signal), enabled: lostAuthorization === null });
  useEffect(() => {
    const logout = (event: Event) => { if (event.target instanceof HTMLFormElement && new URL(event.target.action).pathname === "/api/auth/logout") { activeWrite.current?.abort(); setLostAuthorization(401); } };
    document.addEventListener("submit", logout, true);
    return () => { document.removeEventListener("submit", logout, true); activeWrite.current?.abort(); };
  }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  const deniedStatus = lostAuthorization ?? (query.error instanceof TvtError && (query.error.status === 401 || query.error.status === 403) ? query.error.status : null);
  async function mutate(body: ConsentInput | Preferences, consent: boolean) {
    if (locked.current) return;
    const controller = new AbortController(); activeWrite.current = controller;
    locked.current = true; setBusy(true); setError(""); setNotice("");
    try {
      if (consent) await api.consent(tenantId, body as ConsentInput, controller.signal);
      else await api.preferences(tenantId, body as Preferences, controller.signal);
      if (controller.signal.aborted) return;
      await queryClient.cancelQueries({ queryKey: key });
      await queryClient.fetchQuery({ queryKey: key, queryFn: ({ signal }) => load(signal) });
      if (!controller.signal.aborted) setNotice(consent ? "동의 선택을 저장했습니다." : "설정을 저장했습니다.");
    } catch (cause) {
      if (controller.signal.aborted) return;
      const status = cause instanceof TvtError ? cause.status : 503;
      if (status === 401 || status === 403) loseAccess(status);
      else {
        setError((publicMessages[status] ?? publicMessages[503]).message);
        if (status === 409) {
          await queryClient.cancelQueries({ queryKey: key });
          try { await queryClient.fetchQuery({ queryKey: key, queryFn: ({ signal }) => load(signal) }); } catch { /* The query error renders the safe public state. */ }
        }
      }
    } finally { if (!controller.signal.aborted) { locked.current = false; setBusy(false); } }
  }
  if (deniedStatus === 401) return <div className="wso-card p-6"><p role="alert">로그인 시간이 만료되었습니다. 다시 로그인하세요.</p><a className="wso-button-primary mt-4" href="/api/auth/login">다시 로그인</a></div>;
  if (deniedStatus === 403) return <div className="wso-card p-6"><p role="alert">선택한 조직에 대한 접근 권한을 확인할 수 없습니다. 내 매장에서 다시 선택하세요.</p><a className="wso-button-secondary mt-4" href="/stores">내 매장으로 이동</a></div>;
  if (query.isPending) return <p role="status" aria-live="polite">서비스 정보를 불러오는 중입니다.</p>;
  if (!query.data) return <div className="wso-card p-6"><p role="alert">{query.error instanceof TvtError ? query.error.message : publicMessages[503].message}</p><button className="wso-button-secondary mt-4" onClick={() => void query.refetch()}>다시 시도</button><a className="wso-button-secondary ml-3" href="/stores">내 매장으로 이동</a></div>;
  const bootstrap = query.data;
  return <div className="tvt-shell space-y-6" lang="ko">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">{bootstrap.brand}</h1><p className="mt-2 text-[var(--wso-muted)]">지역: {bootstrap.region}</p></div><FeatureMenu bootstrap={bootstrap} path={path} /></div>
    {(error || query.error) && <p ref={alert} tabIndex={-1} role="alert" className="tvt-error">{error || (query.error instanceof TvtError ? query.error.message : publicMessages[503].message)}</p>}
    {notice && <p role="status" className="text-[var(--wso-success)]">{notice}</p>}
    <DeepLinkResolver path={path} bootstrap={bootstrap}>
      <div className="tvt-panels">
        <div className="space-y-4"><ConsentGate consent={bootstrap.consent} busy={busy} onDecision={body => void mutate(body, true)} />{path === "/tvt/settings" && <Settings key={`${bootstrap.locale}:${bootstrap.timezone}`} bootstrap={bootstrap} busy={busy} onSave={body => void mutate(body, false)} />}</div>
        <aside className="wso-card self-start p-6" aria-label="계정 및 환경"><h2 className="text-lg font-semibold">계정 및 환경</h2><p role="status" className="mt-3">{bootstrap.identity.state === "linked" ? "연결된 TVT 계정이 있습니다." : "연결된 TVT 계정이 없습니다."}</p><p className="mt-3 text-[var(--wso-muted)]">언어: {bootstrap.locale}<br />시간대: {bootstrap.timezone}</p>{bootstrap.consent.decided_at && <p className="mt-3 text-xs text-[var(--wso-muted)]">동의 선택일: <time dateTime={bootstrap.consent.decided_at}>{new Intl.DateTimeFormat(bootstrap.locale, { timeZone: bootstrap.timezone, dateStyle: "medium", timeStyle: "short" }).format(new Date(bootstrap.consent.decided_at))}</time></p>}</aside>
      </div>
    </DeepLinkResolver>
  </div>;
}
