/* eslint-disable @next/next/no-img-element -- Inert owned Blob challenge image; no remote source. */
"use client";
import { useEffect, useRef, useState } from "react";
import { AccountError, imageCheckSchema, loginSchema, type AccountSelection, type ImageChallenge } from "../../../lib/tvt/account-api-client";
import { useAccountSession } from "./SessionBoundary";
import countries from "./countries.json";

// Some source locales repeat or are blank; the source row keeps each option unique.
const countryOptions = countries.map((country, index) => ({ ...country, value: `${country.locale}:${index}` }));
const repeatedChineseLabels = new Set(countries.filter((country, index) => countries.some((other, otherIndex) => otherIndex !== index && other.zh === country.zh && other.code === country.code)).map(country => `${country.zh}:${country.code}`));

function ownedImage(value: ImageChallenge): string {
  const decoded = atob(value.image_base64); const bytes = Uint8Array.from(decoded, character => character.charCodeAt(0));
  const png = bytes.length >= 16 && bytes.slice(0, 8).every((byte, index) => byte === [137, 80, 78, 71, 13, 10, 26, 10][index]) && bytes.slice(-8).every((byte, index) => byte === [73, 69, 78, 68, 174, 66, 96, 130][index]);
  const jpeg = bytes.length >= 5 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 && bytes.at(-2) === 255 && bytes.at(-1) === 217;
  if (bytes.length > 67500 || (value.media_type === "image/png" ? !png : !jpeg) || btoa(decoded) !== value.image_base64) throw new AccountError(503, "ACCOUNT_UNAVAILABLE");
  return URL.createObjectURL(new Blob([bytes], { type: value.media_type }));
}
export function LoginForm({ tenantId, selection }: { tenantId: string; selection: AccountSelection }) {
  const session = useAccountSession();
  const [mode, setMode] = useState<"email" | "phone">("email"); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const [country, setCountry] = useState(""); const [countryLanguage, setCountryLanguage] = useState<"en" | "zh">("en");
  const [challenge, setChallenge] = useState<{ id: string; url: string; expires: number } | null>(null);
  const { requiresFreshImage, setRequiresFreshImage } = session;
  const form = useRef<HTMLFormElement>(null); const alert = useRef<HTMLParagraphElement>(null); const active = useRef<AbortController | null>(null); const imageUrl = useRef<string | null>(null); const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearSecrets = () => { for (const name of ["secret", "image_code", "second_code"]) { const input = form.current?.elements.namedItem(name); if (input instanceof HTMLInputElement) input.value = ""; } };
  const clearImage = () => {
    if (expiryTimer.current) clearTimeout(expiryTimer.current); expiryTimer.current = null;
    if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); imageUrl.current = null; setChallenge(null);
    const code = form.current?.elements.namedItem("image_code"); if (code instanceof HTMLInputElement) code.value = "";
  };
  const changeInput = () => {
    active.current?.abort(); active.current = null; clearSecrets(); clearImage();
    setBusy(false); setError(""); setNotice("");
  };
  useEffect(() => {
    const node = form.current;
    const leave = () => {
      active.current?.abort(); if (expiryTimer.current) clearTimeout(expiryTimer.current); expiryTimer.current = null;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current); imageUrl.current = null;
      for (const input of node?.querySelectorAll("input") ?? []) input.value = "";
    };
    window.addEventListener("pagehide", leave);
    return () => { window.removeEventListener("pagehide", leave); leave(); };
  }, []);
  useEffect(() => { if (error) alert.current?.focus(); }, [error]);
  async function request(kind: "login" | "image" | "check") {
    if (active.current) return;
    const values = new FormData(form.current!); const text = (name: string) => String(values.get(name) ?? "");
    if (kind !== "image" && challenge && Date.now() >= challenge.expires) { clearImage(); clearSecrets(); setRequiresFreshImage(true); setError("이미지 확인 시간이 만료되었습니다. 새 이미지를 요청하세요."); return; }
    if (kind === "login" && requiresFreshImage && !challenge) { clearSecrets(); setError("사용한 확인 이미지를 다시 사용할 수 없습니다. 로그인하려면 새 확인 이미지를 요청하세요."); return; }
    const selectedCountry = countryOptions.find(option => option.value === country);
    const login = loginSchema.safeParse({ ...selection, mode, ...(mode === "phone" ? { country_code: selectedCountry ? String(selectedCountry.code) : undefined } : {}), account: text("account"), secret: text("secret"), ...(challenge ? { challenge_id: challenge.id, image_code: text("image_code") } : {}), ...(text("second_code") ? { second_code: text("second_code") } : {}) });
    const check = imageCheckSchema.safeParse({ ...selection, challenge_id: challenge?.id, image_code: text("image_code") });
    if ((kind === "login" && !login.success) || (kind === "check" && !check.success)) { setError("계정과 비밀번호, 확인 코드 형식을 확인하세요."); clearSecrets(); return; }
    const controller = new AbortController(); active.current = controller; setBusy(true); setError(""); setNotice("");
    if (kind !== "image" && challenge) setRequiresFreshImage(true);
    // A submitted or checked challenge is locally consumed before dispatch too.
    clearImage();
    try {
      if (kind === "image") {
        const value = await session.execute(signal => session.api.image(tenantId, selection, AbortSignal.any([signal, controller.signal])));
        controller.signal.throwIfAborted(); const url = ownedImage(value); imageUrl.current = url; setRequiresFreshImage(false);
        setChallenge({ id: value.challenge_id, url, expires: Date.now() + value.expires_in_seconds * 1000 });
        expiryTimer.current = setTimeout(() => { clearImage(); clearSecrets(); setRequiresFreshImage(true); setError("이미지 확인 시간이 만료되었습니다. 새 이미지를 요청하세요."); }, value.expires_in_seconds * 1000);
      } else if (kind === "check" && check.success) {
        await session.execute(signal => session.api.check(tenantId, check.data, AbortSignal.any([signal, controller.signal])));
        controller.signal.throwIfAborted(); setNotice("이미지 코드를 확인했습니다. 로그인하려면 확인 이미지를 새로 요청하세요.");
      } else if (login.success) {
        await session.execute(signal => session.api.login(tenantId, login.data, AbortSignal.any([signal, controller.signal])));
        controller.signal.throwIfAborted(); form.current?.reset(); await session.requery();
        if (!controller.signal.aborted) setNotice("TVT 계정 로그인 상태를 확인했습니다.");
      }
    } catch (cause) {
      if (!controller.signal.aborted && !(cause instanceof DOMException && cause.name === "AbortError")) await session.report(cause);
    } finally {
      if (active.current === controller) {
        clearSecrets(); active.current = null;
        if (!controller.signal.aborted) setBusy(false);
      }
    }
  }
  return <section className="wso-card p-6" aria-labelledby="tvt-login-title"><h2 id="tvt-login-title" className="text-lg font-semibold">TVT 계정 로그인</h2><p className="mt-2 text-[var(--wso-muted)]">지역: {selection.region}</p>
    {error && <p ref={alert} role="alert" tabIndex={-1} className="tvt-error mt-4">{error}</p>}{notice && <p role="status" className="mt-4">{notice}</p>}
    <form ref={form} className="mt-5 space-y-4" aria-busy={busy} noValidate autoComplete="off" onSubmit={event => { event.preventDefault(); void request("login"); }}>
      <div><label className="mb-2 block font-medium" htmlFor="tvt-login-mode">로그인 방식</label><select id="tvt-login-mode" className="tvt-input" value={mode} onChange={event => { const nextMode = event.target.value as "email" | "phone"; if (nextMode === mode) return; changeInput(); form.current?.reset(); setCountry(""); setCountryLanguage(document.documentElement.lang.toLowerCase().startsWith("zh") ? "zh" : "en"); setMode(nextMode); }}><option value="email">이메일</option><option value="phone">전화번호</option></select></div>
      {mode === "phone" && <div><label className="mb-2 block font-medium" htmlFor="tvt-country-code">국가 전화 코드</label><select id="tvt-country-code" className="tvt-input" value={country} required onChange={event => { if (event.target.value === country) return; changeInput(); setCountry(event.target.value); }}><option value="">국가 전화 코드를 선택하세요</option>{countryOptions.map(option => <option key={option.value} value={option.value}>{option[countryLanguage]}{countryLanguage === "zh" && repeatedChineseLabels.has(`${option.zh}:${option.code}`) ? ` / ${option.en}` : ""} (+{option.code})</option>)}</select></div>}
      <div><label className="mb-2 block font-medium" htmlFor="tvt-account-name">{mode === "email" ? "이메일" : "전화번호"}</label><input key={mode} id="tvt-account-name" name="account" className="tvt-input" type={mode === "email" ? "email" : "tel"} inputMode={mode === "phone" ? "numeric" : "email"} maxLength={mode === "phone" ? 32 : 512} disabled={busy} required autoComplete="off" /></div>
      <div><label className="mb-2 block font-medium" htmlFor="tvt-password">비밀번호</label><input id="tvt-password" name="secret" className="tvt-input" type="password" maxLength={4096} disabled={busy} required autoComplete="off" /></div>
      {challenge && <div className="space-y-3"><img src={challenge.url} alt="로그인 확인 이미지" className="max-w-full rounded-lg" /><p className="text-xs text-[var(--wso-muted)]">이미지 확인은 120초 동안 유효하며 한 번 사용할 수 있습니다.</p><label className="block font-medium" htmlFor="tvt-image-code">이미지 확인 코드</label><input className="tvt-input" id="tvt-image-code" name="image_code" maxLength={256} disabled={busy} autoComplete="off" /><button className="wso-button-secondary" type="button" disabled={busy} onClick={() => void request("check")}>이미지 코드 확인</button></div>}
      <div><label className="mb-2 block font-medium" htmlFor="tvt-second-code">추가 확인 코드</label><input className="tvt-input" id="tvt-second-code" name="second_code" maxLength={256} disabled={busy} autoComplete="off" /><p className="mt-2 text-xs text-[var(--wso-muted)]">계정에 추가 확인이 필요한 경우 입력하세요.</p></div>
      <div className="flex flex-wrap gap-3"><button className="wso-button-primary" disabled={busy} type="submit">TVT 로그인</button><button className="wso-button-secondary" disabled={busy} type="button" onClick={() => void request("image")}>{challenge ? "이미지 새로 요청" : "이미지 확인 요청"}</button><button className="wso-button-secondary" type="button" onClick={() => { active.current?.abort(); active.current = null; clearSecrets(); clearImage(); form.current?.reset(); setBusy(false); setError(""); setNotice(""); }}>취소</button></div>
    </form>
  </section>;
}
