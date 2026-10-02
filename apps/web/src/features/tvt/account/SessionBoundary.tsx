"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AccountError, accountClient, type AccountApi } from "../../../lib/tvt/account-api-client";
import { AccountFlowError, accountFlowClient, safeFlowError, type AccountFlowApi } from "../../../lib/tvt/flow-api-client";
import type { Bootstrap } from "../../../lib/tvt/api-client";
import { LoginForm } from "./LoginForm";
import { Profile } from "./Profile";
import { RegisterForm } from "./RegisterForm";
import { RecoverForm } from "./RecoverForm";

type Session = {
  api: AccountApi;
  flowApi: AccountFlowApi;
  flowPolicies: { terms: string; privacy: string };
  authorityEpoch: () => number;
  execute: <T>(operation: (signal: AbortSignal) => Promise<T>) => Promise<T>;
  report: (error: unknown) => Promise<void>;
  requery: () => Promise<Bootstrap>;
  requiresFreshImage: boolean;
  setRequiresFreshImage: (required: boolean) => void;
};
const AccountSession = createContext<Session | null>(null);
export function useAccountSession() {
  const value = useContext(AccountSession); if (!value) throw new Error("Account session unavailable"); return value;
}
export function SessionBoundary({ userId, bootstrap, csrf, requery }: { userId: string; bootstrap: Bootstrap; csrf: string; requery: () => Promise<Bootstrap> }) {
  const scope = [userId, bootstrap.selected_tenant_id, bootstrap.profile_id, bootstrap.brand, bootstrap.region, bootstrap.consent.version, bootstrap.consent.status, ...bootstrap.identity.accounts.map(item => `${item.id}:${item.brand}:${item.region}`)].join(":");
  if (bootstrap.consent.status !== "accepted") return <p role="status" className="wso-card p-6">현재 약관에 동의한 뒤 TVT 계정을 이용하세요.</p>;
  return <ActiveAccount key={scope + ":" + csrf} bootstrap={bootstrap} csrf={csrf} requery={requery} />;
}
function ActiveAccount({ bootstrap, csrf, requery }: { bootstrap: Bootstrap; csrf: string; requery: () => Promise<Bootstrap> }) {
  const [api] = useState(() => accountClient(csrf));
  const [flowApi] = useState(() => accountFlowClient(csrf));
  const [entry, setEntry] = useState<"login" | "register" | "recover">("login");
  const [entryVersion, setEntryVersion] = useState(0);
  const accounts = bootstrap.identity.accounts.filter(item => item.brand === bootstrap.brand && item.region === bootstrap.region);
  const [selected, setSelected] = useState(accounts[0]?.id ?? "");
  // Only this non-secret latch survives temporary authority checks in this scope.
  const [requiresFreshImage, setRequiresFreshImage] = useState(false);
  const [message, setMessage] = useState(""); const [checking, setChecking] = useState(false); const [blocked, setBlocked] = useState(false);
  const epoch = useRef(0); const pending = useRef(new Set<AbortController>()); const alert = useRef<HTMLParagraphElement>(null);
  const cancel = useCallback(() => { epoch.current++; for (const controller of pending.current) controller.abort(); pending.current.clear(); }, []);
  useEffect(() => {
    const leave = () => { cancel(); setBlocked(true); };
    const logout = (event: Event) => { if (event.target instanceof HTMLFormElement && new URL(event.target.action).pathname === "/api/auth/logout") { cancel(); setBlocked(true); } };
    window.addEventListener("pagehide", leave); document.addEventListener("submit", logout, true);
    return () => { window.removeEventListener("pagehide", leave); document.removeEventListener("submit", logout, true); cancel(); };
  }, [cancel]);
  useEffect(() => { if (message) alert.current?.focus(); }, [message]);
  const execute = useCallback(async <T,>(operation: (signal: AbortSignal) => Promise<T>) => {
    const stamp = epoch.current; const controller = new AbortController(); pending.current.add(controller);
    try {
      const value = await operation(controller.signal);
      if (controller.signal.aborted || epoch.current !== stamp) throw new DOMException("Cancelled", "AbortError");
      return value;
    } finally { pending.current.delete(controller); }
  }, []);
  const report = async (error: unknown) => {
    if (error instanceof DOMException && error.name === "AbortError") return;
    const failure = error instanceof AccountFlowError ? safeFlowError(error.status, { error: { code: error.code }, request_id: "ui:failure" }) : null;
    const safe = failure ? new AccountFlowError(failure.status, failure.error.code, failure.error.message) : error instanceof AccountError ? error : new AccountError(503, "ACCOUNT_UNAVAILABLE");
    setMessage(safe.message);
    if ([401, 403, 409, 504].includes(safe.status)) {
      cancel(); setChecking(true); const stamp = epoch.current;
      try {
        const authority = await requery();
        if (epoch.current === stamp) setBlocked(authority.consent.status !== "accepted" || authority.brand !== bootstrap.brand || authority.region !== bootstrap.region);
      } catch { if (epoch.current === stamp) setBlocked(true); }
      finally { if (epoch.current === stamp) setChecking(false); }
    }
  };
  const context: Session = { api, flowApi, flowPolicies: { terms: bootstrap.consent.terms.url, privacy: bootstrap.consent.privacy.url }, authorityEpoch: () => epoch.current, execute, report, requery: async () => {
    cancel(); setChecking(true); const stamp = epoch.current;
    try { return await requery(); }
    catch (error) { if (stamp === epoch.current) setBlocked(true); throw error; }
    finally { if (stamp === epoch.current) setChecking(false); }
  }, requiresFreshImage, setRequiresFreshImage };
  const navigate = (next: "login" | "register" | "recover") => { cancel(); setMessage(""); setEntry(next); setEntryVersion(value => value + 1); };
  return <AccountSession.Provider value={context}>
    <section className="space-y-4" aria-label="TVT 계정">
      {message && <p ref={alert} tabIndex={-1} role="alert" className="tvt-error">{message}</p>}
      {checking ? <p role="status">현재 계정과 웹 로그인 권한을 확인합니다.</p> : blocked ? <div className="wso-card p-6"><p role="status">현재 계정 권한을 확인할 수 없습니다. 페이지를 다시 열어주세요.</p></div> : <>
        {accounts.length > 0 && <div className="wso-card p-6"><label htmlFor="tvt-identity" className="mb-2 block font-medium">연결된 TVT 계정</label><select id="tvt-identity" className="tvt-input" value={selected} onChange={event => { if (event.target.value === selected) return; cancel(); setMessage(""); setRequiresFreshImage(false); setSelected(event.target.value); }}>{accounts.map(item => <option key={item.id} value={item.id}>{item.id} · {item.region}</option>)}</select></div>}
        {selected && accounts.some(item => item.id === selected) && <Profile key={`profile:${selected}`} tenantId={bootstrap.selected_tenant_id} identityId={selected} selection={{ brand: bootstrap.brand, region: bootstrap.region }} />}
        <nav aria-label="계정 작업" className="flex flex-wrap gap-3">
          <button type="button" className="wso-button-secondary" aria-current={entry === "login" ? "page" : undefined} onClick={() => navigate("login")}>계정 로그인</button>
          <button type="button" className="wso-button-secondary" aria-current={entry === "register" ? "page" : undefined} onClick={() => navigate("register")}>계정 등록</button>
          <button type="button" className="wso-button-secondary" aria-current={entry === "recover" ? "page" : undefined} onClick={() => navigate("recover")}>비밀번호 찾기</button>
        </nav>
        {entry === "login" ? <LoginForm key={`login:${selected || "new"}:${entryVersion}`} tenantId={bootstrap.selected_tenant_id} selection={{ brand: bootstrap.brand, region: bootstrap.region }} /> : entry === "register" ? <RegisterForm key={`register:${selected || "new"}:${entryVersion}`} tenantId={bootstrap.selected_tenant_id} selection={{ brand: bootstrap.brand, region: bootstrap.region }} onReturnToLogin={() => navigate("login")} /> : <RecoverForm key={`recover:${selected || "new"}:${entryVersion}`} tenantId={bootstrap.selected_tenant_id} selection={{ brand: bootstrap.brand, region: bootstrap.region }} onReturnToLogin={() => navigate("login")} />}
      </>}
    </section>
  </AccountSession.Provider>;
}
