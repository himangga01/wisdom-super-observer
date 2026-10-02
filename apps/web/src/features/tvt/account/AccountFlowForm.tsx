/* eslint-disable @next/next/no-img-element -- Inert owned Blob challenge; no remote source. */
"use client";
import { useEffect, useRef, useState } from "react";
import { AccountFlowError, safeFlowError, flowStartSchema, flowRegisterSchema, flowRecoverSchema, type AccountFlowReference, type AccountFlowView } from "../../../lib/tvt/flow-api-client";
import type { AccountSelection } from "../../../lib/tvt/account-api-client";
import { useAccountSession } from "./SessionBoundary";
import countries from "./countries.json";

const countryOptions = countries.map((country, index) => ({ ...country, value: `${country.locale}:${index}` }));
const repeatedChineseLabels = new Set(countries.filter((country, index) => countries.some((other, otherIndex) => otherIndex !== index && other.zh === country.zh && other.code === country.code)).map(country => `${country.zh}:${country.code}`));
const terminal = new Set(["FAILED", "CLOSED", "EXPIRED"]);
const unknownMessage = "처리 결과를 확인할 수 없습니다. 다시 제출하지 말고 현재 상태를 확인하세요. 확인되지 않으면 지원 담당자에게 문의하세요.";
// classes4.dex yg3.b: punctuation match + ASCII letter match + digit match >= 2.
// Java Pattern's dot does not match these line terminators.
function passwordReady(value: string) {
  if (value.length < 8 || value.length > 16 || /[\n\r\u0085\u2028\u2029]/.test(value)) return false;
  const punctuation = /[`~!@#$%^&*()+=|{}'":;,\[\].<>＜＞《》～/?！￥¥€£•…（）—【】「」『』‘；：”“’。，、？]/.test(value);
  return Number(punctuation) + Number(/[a-zA-Z]/.test(value)) + Number(/[0-9]/.test(value)) >= 2;
}
function ownedImage(value: NonNullable<AccountFlowView["image"]>) {
  const decoded = atob(value.image_base64);
  const bytes = Uint8Array.from(decoded, character => character.charCodeAt(0));
  const png = bytes.length >= 16 && bytes.slice(0, 8).every((byte, index) => byte === [137, 80, 78, 71, 13, 10, 26, 10][index]) && bytes.slice(-8).every((byte, index) => byte === [73, 69, 78, 68, 174, 66, 96, 130][index]);
  const jpeg = bytes.length >= 5 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 && bytes.at(-2) === 255 && bytes.at(-1) === 217;
  if (bytes.length > 65536 || btoa(decoded) !== value.image_base64 || (value.media_type === "image/png" ? !png : value.media_type === "image/jpeg" ? !jpeg : true)) throw new AccountFlowError(503, "ACCOUNT_PROTOCOL_INVALID", "확인 이미지를 불러올 수 없습니다.");
  return URL.createObjectURL(new Blob([bytes], { type: value.media_type }));
}
export type AccountFlowFormProps = { tenantId: string; selection: AccountSelection; onReturnToLogin: () => void };
export function AccountFlowForm({ tenantId, selection, purpose, onReturnToLogin }: AccountFlowFormProps & { purpose: "register" | "recover" }) {
  // A scope replacement destroys the entire controller, timers and secret inputs.
  return <ScopedAccountFlow key={[tenantId, selection.brand, selection.region, purpose].join(":")} tenantId={tenantId} selection={selection} purpose={purpose} onReturnToLogin={onReturnToLogin} />;
}
function ScopedAccountFlow({ tenantId, selection, purpose, onReturnToLogin }: AccountFlowFormProps & { purpose: "register" | "recover" }) {
  const session = useAccountSession();
  const [mode, setMode] = useState<"email" | "phone">("email");
  const [country, setCountry] = useState("");
  const [countryLanguage, setCountryLanguage] = useState<"en" | "zh">("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [state, setState] = useState<AccountFlowView["state"] | null>(null);
  const [image, setImage] = useState<{ url: string; id: string; generation: number } | null>(null);
  const [imageLength, setImageLength] = useState(0);
  const [wait, setWait] = useState(0);
  const [hasFlow, setHasFlow] = useState(false);
  const [blockedFinal, setBlockedFinal] = useState(false);
  const form = useRef<HTMLFormElement>(null);
  const alert = useRef<HTMLParagraphElement>(null);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const flow = useRef<AccountFlowReference | null>(null);
  const existenceVerified = useRef(false);
  const finalSubmitted = useRef(false);
  const imageUrl = useRef<string | null>(null);
  const expiresAt = useRef<number | null>(null);
  const resendAt = useRef<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const clearInputs = (all = false) => {
    for (const input of form.current?.querySelectorAll("input") ?? []) {
      if (all || ["password", "dynamic_code", "image_code"].includes(input.name)) {
        if (input.type === "checkbox") input.checked = false; else input.value = "";
      }
    }
    setImageLength(0);
  };
  const clearImage = () => {
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
    imageUrl.current = null; setImage(null); setImageLength(0);
    const input = form.current?.elements.namedItem("image_code");
    if (input instanceof HTMLInputElement) input.value = "";
  };
  const clearTimer = () => {
    if (timer.current !== null) clearInterval(timer.current);
    timer.current = null; expiresAt.current = null; resendAt.current = null; setWait(0);
  };
  const invalidate = (all = false) => {
    generation.current++; active.current?.abort(); active.current = null;
    flow.current = null; existenceVerified.current = false; finalSubmitted.current = false; setHasFlow(false); setBlockedFinal(false);
    clearTimer(); clearImage(); clearInputs(all);
    setBusy(false); setState(null); setError(""); setNotice("");
  };
  // The mount owns this DOM node and URL even after its replacement is rendered.
  useEffect(() => {
    const node = form.current;
    const leave = () => {
      generation.current++; active.current?.abort(); active.current = null;
      flow.current = null; existenceVerified.current = false; finalSubmitted.current = false;
      if (timer.current !== null) clearInterval(timer.current); timer.current = null;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); imageUrl.current = null;
      for (const input of node?.querySelectorAll("input") ?? []) { input.value = ""; input.checked = false; }
    };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); leave(); };
  }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  const expire = () => {
    const uncertain = finalSubmitted.current;
    generation.current++; active.current?.abort(); active.current = null;
    clearTimer(); clearImage(); clearInputs(true); setBusy(false);
    if (!uncertain) flow.current = null;
    existenceVerified.current = false;
    setHasFlow(uncertain); setBlockedFinal(uncertain);
    setState(uncertain ? "UNKNOWN_OUTCOME" : "EXPIRED");
    setNotice(""); setError(uncertain ? unknownMessage : "계정 확인 시간이 만료되었습니다. 새로 시작하세요.");
  };
  const updateTimer = (value: AccountFlowView) => {
    // Public expiry is local flow lifetime, never a vendor dynamic-code TTL.
    if (value.expires_in_seconds != null) {
      const next = Date.now() + value.expires_in_seconds * 1000;
      expiresAt.current = expiresAt.current === null ? next : Math.min(expiresAt.current, next);
    }
    if (value.state === "CODE_SENT") {
      resendAt.current = Date.now() + (value.resend_wait_seconds ?? 120) * 1000;
      setWait(Math.max(0, Math.ceil((resendAt.current - Date.now()) / 1000)));
    }
    if (timer.current === null && (expiresAt.current !== null || resendAt.current !== null)) {
      timer.current = setInterval(() => {
        if (expiresAt.current !== null && Date.now() >= expiresAt.current) { expire(); return; }
        setWait(resendAt.current === null ? 0 : Math.max(0, Math.ceil((resendAt.current - Date.now()) / 1000)));
        if (resendAt.current !== null && Date.now() >= resendAt.current) resendAt.current = null;
      }, 1000);
    }
  };
  const apply = (value: AccountFlowView) => {
    if (finalSubmitted.current && !terminal.has(value.state) && !["COMPLETE", "UNKNOWN_OUTCOME"].includes(value.state)) {
      clearTimer(); clearImage(); clearInputs(true); setState("UNKNOWN_OUTCOME"); setBlockedFinal(true); setNotice(""); setError(unknownMessage); return;
    }
    updateTimer(value); setState(value.state); clearImage();
    if (value.state === "COMPLETE") { invalidate(true); onReturnToLogin(); return; }
    if (terminal.has(value.state)) {
      flow.current = null; existenceVerified.current = false; setHasFlow(false); clearTimer(); clearInputs(true);
      setNotice(""); setError(value.state === "EXPIRED" ? "계정 확인 시간이 만료되었습니다. 새로 시작하세요." : value.state === "CLOSED" ? "계정 요청이 닫혔습니다. 새로 시작하세요." : "계정 요청을 완료할 수 없습니다. 내용을 확인하고 새로 시작하세요.");
      return;
    }
    if (value.state === "UNKNOWN_OUTCOME") {
      finalSubmitted.current = true; setBlockedFinal(true); clearTimer(); clearInputs(true); setNotice(""); setError(unknownMessage); return;
    }
    if (value.image) {
      const url = ownedImage(value.image); imageUrl.current = url;
      setImage({ url, id: value.image.challenge_id, generation: value.image.generation });
      setNotice(value.state === "IMAGE_REJECTED" ? "이미지 코드가 맞지 않습니다. 새 이미지의 코드를 입력하세요." : "확인 이미지의 코드를 입력한 뒤 확인 코드를 요청하세요.");
    } else if (value.state === "CODE_SENT") setNotice("확인 코드를 보냈습니다. 받은 여섯 글자 코드를 입력하세요.");
  };
  async function request(kind: "code" | "image" | "final" | "state") {
    if (active.current || (finalSubmitted.current && kind !== "state") || terminal.has(state ?? "")) return;
    if (expiresAt.current !== null && Date.now() >= expiresAt.current && kind !== "state") { expire(); return; }
    if (kind === "code" && resendAt.current !== null && Date.now() < resendAt.current) return;
    const values = new FormData(form.current!);
    const text = (name: string) => String(values.get(name) ?? "");
    const selectedCountry = countryOptions.find(option => option.value === country);
    const start = flowStartSchema.safeParse({ ...selection, purpose, mode, account: text("account"), ...(mode === "phone" ? { country_code: selectedCountry ? String(selectedCountry.code) : undefined } : {}) });
    if (kind !== "state" && (!start.success || (purpose === "register" && values.get("agreement") !== "on"))) {
      setError("계정 형식을 확인하고 서비스 약관과 개인정보 처리방침에 동의하세요."); clearInputs(); return;
    }
    if (kind === "final" && (state !== "CODE_SENT" || !passwordReady(text("password")) || text("dynamic_code").length !== 6)) {
      setError("새 비밀번호는 8–16글자이며 영문, 숫자, 지원 기호 중 두 종류가 필요합니다. 확인 코드는 여섯 글자입니다."); clearInputs(); return;
    }
    if (image && kind === "code" && text("image_code").length < (purpose === "register" ? 6 : 4)) return;
    const currentImage = image;
    const stamp = generation.current;
    const authorityStamp = session.authorityEpoch();
    const controller = new AbortController(); active.current = controller;
    const owns = () => active.current === controller && generation.current === stamp && session.authorityEpoch() === authorityStamp && !controller.signal.aborted;
    const invoke = <T,>(operation: (signal: AbortSignal) => Promise<T>) => session.execute(signal => operation(AbortSignal.any([signal, controller.signal])));
    setBusy(true); setError(""); setNotice("");
    if (kind === "code" && currentImage) clearImage();
    try {
      if (!flow.current && start.success && kind !== "state") {
        const created = await invoke(signal => session.flowApi.start(tenantId, start.data, signal));
        if (!owns()) return;
        flow.current = { ...selection, purpose, flow_id: created.flow_id }; setHasFlow(true); apply(created);
        if (!flow.current || finalSubmitted.current) return;
        const existence = await invoke(signal => session.flowApi.existence(tenantId, flow.current!, signal));
        if (!owns()) return;
        apply(existence);
        if (existence.state !== "EXISTENCE" || existence.exists !== (purpose === "recover")) {
          if (existence.state === "EXISTENCE") {
            flow.current = null; setHasFlow(false); clearTimer(); clearInputs(true); setState("FAILED");
            setError(purpose === "register" ? "이미 등록된 계정입니다. 로그인하거나 비밀번호를 찾으세요." : "등록된 계정을 확인할 수 없습니다. 계정 정보를 확인하세요.");
          }
          return;
        }
        existenceVerified.current = true;
      }
      const reference = flow.current;
      if (!reference || !owns() || (kind !== "state" && !existenceVerified.current)) return;
      let result: AccountFlowView;
      if (kind === "code") result = await invoke(signal => session.flowApi.issueCode(tenantId, { ...reference, ...(currentImage ? { challenge_id: currentImage.id, challenge_generation: currentImage.generation, image_code: text("image_code") } : {}) }, signal));
      else if (kind === "image") result = await invoke(signal => session.flowApi.image(tenantId, reference, signal));
      else if (kind === "state") result = await invoke(signal => session.flowApi.state(tenantId, reference, signal));
      else {
        if (purpose === "register") {
          const body = flowRegisterSchema.safeParse({ ...reference, purpose, password: text("password"), dynamic_code: text("dynamic_code") });
          if (!body.success) { setError("비밀번호와 확인 코드 형식을 확인하세요. 지원하지 않는 문자가 포함되어 있습니다."); return; }
          finalSubmitted.current = true; setBlockedFinal(true);
          result = await invoke(signal => session.flowApi.register(tenantId, body.data, signal));
        } else {
          const body = flowRecoverSchema.safeParse({ ...reference, purpose, new_password: text("password"), dynamic_code: text("dynamic_code") });
          if (!body.success) { setError("비밀번호와 확인 코드 형식을 확인하세요. 지원하지 않는 문자가 포함되어 있습니다."); return; }
          finalSubmitted.current = true; setBlockedFinal(true);
          result = await invoke(signal => session.flowApi.recover(tenantId, body.data, signal));
        }
      }
      if (owns()) apply(result);
    } catch (cause) {
      if (!owns() || (cause instanceof DOMException && cause.name === "AbortError")) return;
      clearImage();
      if (kind === "final") {
        setState("UNKNOWN_OUTCOME"); clearTimer(); clearInputs(true); setError(unknownMessage);
        if (cause instanceof AccountFlowError && [401, 403].includes(cause.status)) await session.report(cause);
      } else {
        // Creating a handle is not proof of purpose-appropriate existence.
        // An exception before verification closes the local attempt; retries
        // must start a fresh flow and complete its own existence check.
        if (kind !== "state" && !finalSubmitted.current && flow.current && !existenceVerified.current) {
          flow.current = null; setHasFlow(false); clearTimer(); clearInputs(true); setState("FAILED");
        }
        setError(kind === "state" && finalSubmitted.current ? unknownMessage : cause instanceof AccountFlowError ? safeFlowError(cause.status, { error: { code: cause.code }, request_id: "ui:failure" }).error.message : "계정 요청을 확인할 수 없습니다. 잠시 후 다시 확인하세요.");
        await session.report(cause);
      }
    } finally {
      // Both result and finally belong to exactly the dispatching form.
      if (owns()) { clearInputs(); active.current = null; setBusy(false); }
    }
  }
  const cancel = (returnToLogin = false) => {
    const reference = finalSubmitted.current ? null : flow.current;
    invalidate(true);
    // Explicit cancellation is bounded under the current session; local cleanup
    // happens first and its outcome cannot change the replacement form.
    if (reference) void session.execute(signal => session.flowApi.cancel(tenantId, reference, AbortSignal.any([signal, AbortSignal.timeout(1500)]))).catch(() => {});
    if (returnToLogin) onReturnToLogin();
  };
  const stopped = terminal.has(state ?? "") || state === "UNKNOWN_OUTCOME";
  return <section className="wso-card p-6" aria-labelledby="tvt-flow-title">
    <h2 id="tvt-flow-title" className="text-lg font-semibold">{purpose === "register" ? "TVT 계정 등록" : "TVT 비밀번호 찾기"}</h2>
    <p className="mt-2 text-[var(--wso-muted)]">지역: {selection.region}</p>
    {error && <p ref={alert} tabIndex={-1} role="alert" className="tvt-error mt-4">{error}</p>}
    {notice && <p role="status" className="mt-4">{notice}</p>}
    <form ref={form} noValidate autoComplete="off" className="mt-5 space-y-4" aria-busy={busy} onSubmit={event => { event.preventDefault(); void request("final"); }}>
      <div><label htmlFor="tvt-flow-mode" className="mb-2 block font-medium">계정 방식</label><select id="tvt-flow-mode" className="tvt-input" value={mode} onChange={event => {
        if (event.target.value === mode) return; invalidate(true); setCountry(""); setCountryLanguage(document.documentElement.lang.toLowerCase().startsWith("zh") ? "zh" : "en"); setMode(event.target.value as "email" | "phone");
      }}><option value="email">이메일</option><option value="phone">전화번호</option></select></div>
      {mode === "phone" && <div><label htmlFor="tvt-flow-country" className="mb-2 block font-medium">국가 전화 코드</label><select id="tvt-flow-country" className="tvt-input" value={country} onChange={event => { if (event.target.value === country) return; invalidate(); setCountry(event.target.value); }}><option value="">국가 전화 코드를 선택하세요</option>{countryOptions.map(option => <option key={option.value} value={option.value}>{option[countryLanguage]}{countryLanguage === "zh" && repeatedChineseLabels.has(`${option.zh}:${option.code}`) ? ` / ${option.en}` : ""} (+{option.code})</option>)}</select></div>}
      <div><label htmlFor="tvt-flow-account" className="mb-2 block font-medium">{mode === "email" ? "이메일" : "전화번호"}</label><input key={mode} id="tvt-flow-account" name="account" className="tvt-input" type={mode === "email" ? "email" : "tel"} inputMode={mode === "phone" ? "numeric" : "email"} maxLength={mode === "phone" ? 32 : 512} autoComplete="off" onChange={() => invalidate()} /></div>
      {purpose === "register" && <label className="flex items-start gap-3"><input type="checkbox" name="agreement" onChange={() => invalidate()} className="mt-1" /><span>서비스 약관과 개인정보 처리방침에 동의합니다. <a className="underline" href={session.flowPolicies.terms} target="_blank" rel="noreferrer">서비스 약관</a> · <a className="underline" href={session.flowPolicies.privacy} target="_blank" rel="noreferrer">개인정보 처리방침</a></span></label>}
      {image && <div className="space-y-3"><img src={image.url} alt="계정 확인 이미지" className="max-w-full rounded-lg" /><label htmlFor="tvt-flow-image" className="block font-medium">이미지 확인 코드</label><input id="tvt-flow-image" name="image_code" className="tvt-input" maxLength={256} disabled={busy} autoComplete="off" onChange={event => setImageLength(event.target.value.length)} /><button type="button" className="wso-button-secondary" disabled={busy || stopped || imageLength < (purpose === "register" ? 6 : 4)} onClick={() => void request("code")}>이미지 확인 후 코드 요청</button></div>}
      <div><label htmlFor="tvt-flow-code" className="mb-2 block font-medium">확인 코드</label><input id="tvt-flow-code" name="dynamic_code" className="tvt-input" maxLength={6} disabled={busy || stopped} autoComplete="off" /></div>
      <div><label htmlFor="tvt-flow-password" className="mb-2 block font-medium">새 비밀번호</label><input id="tvt-flow-password" name="password" type="password" className="tvt-input" maxLength={16} disabled={busy || stopped} autoComplete="off" /><p className="mt-2 text-xs text-[var(--wso-muted)]">8–16글자, 영문·숫자·지원 기호 중 두 종류</p></div>
      {wait > 0 && <p role="status">{wait}초 후 확인 코드를 다시 요청할 수 있습니다.</p>}
      <div className="flex flex-wrap gap-3">
        <button className="wso-button-secondary" type="button" disabled={busy || stopped || wait > 0 || !!image} onClick={() => void request("code")}>{state === "CODE_SENT" ? "확인 코드 다시 요청" : "확인 코드 요청"}</button>
        {hasFlow && !stopped && <button className="wso-button-secondary" type="button" disabled={busy || wait > 0} onClick={() => void request("image")}>이미지 새로 요청</button>}
        <button className="wso-button-primary" type="submit" disabled={busy || stopped || state !== "CODE_SENT" || blockedFinal}>{purpose === "register" ? "등록 완료" : "비밀번호 변경"}</button>
        {state === "UNKNOWN_OUTCOME" && hasFlow && <button className="wso-button-secondary" type="button" disabled={busy} onClick={() => void request("state")}>현재 상태 확인</button>}
        {terminal.has(state ?? "") && <button className="wso-button-secondary" type="button" onClick={() => invalidate(true)}>새로 시작</button>}
        <button className="wso-button-secondary" type="button" onClick={() => cancel()}>취소</button>
        <button className="wso-button-secondary" type="button" onClick={() => cancel(true)}>로그인으로 돌아가기</button>
      </div>
    </form>
  </section>;
}
