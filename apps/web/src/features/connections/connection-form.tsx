"use client";
import { useEffect, useRef, useState, type FormEvent, type ChangeEvent } from "react";
import { decodeDeviceQrImage } from "../../lib/tvt/device-qr-image";
import type { Store } from "../../lib/session";
import {
  connectionKinds,
  kindLabel,
  parseConnectionBody,
  type ConnectionView,
} from "../../lib/connections";
const inputClass =
  "mt-2 block w-full min-w-0 rounded-lg border border-[var(--wso-border)] bg-white px-3 py-2.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#226594]";
export function ConnectionForm({
  connection,
  stores,
  busy,
  onSubmit,
  onCancel,
}: {
  connection?: ConnectionView;
  stores: Store[];
  busy: boolean;
  onSubmit: (body: unknown) => Promise<void>;
  onCancel: () => void;
}) {
  const [replacement, setReplacement] = useState(false);
  const [validation, setValidation] = useState("");
  const [kind, setKind] = useState(connection?.kind ?? "TVT_ACCOUNT");
  const [reading, setReading] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const decodeGeneration = useRef(0);
  const qrPayload = useRef<string | undefined>(undefined);
  const scopeKey = stores.map(store => `${store.tenant_id}/${store.id}`).join(",");
  function clearPrivate() {
    decodeGeneration.current += 1;
    qrPayload.current = undefined;
    setReading(false);
    for (const name of ["username", "password", "device_serial", "device_qr_image"]) {
      const input = formRef.current?.elements.namedItem(name) as HTMLInputElement | null;
      if (input) input.value = "";
    }
    const country = formRef.current?.elements.namedItem("device_country") as HTMLInputElement | null;
    if (country) country.value = "KR";
  }
  useEffect(() => {
    const form = formRef.current;
    return () => {
      decodeGeneration.current += 1; qrPayload.current = undefined;
      setReading(false);
      form?.querySelectorAll<HTMLInputElement>('[name="username"], [name="password"], [name="device_serial"], [name="device_qr_image"]').forEach(input => { input.value = ""; });
      const country = form?.elements.namedItem("device_country") as HTMLInputElement | null;
      if (country) country.value = "KR";
    };
  }, [connection?.id, connection?.tenant_id, connection?.generation, scopeKey]);
  async function readQr(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    clearPrivate();
    if (!file) return;
    const generation = decodeGeneration.current;
    setReading(true); setValidation("");
    try {
      const result = await decodeDeviceQrImage(file);
      if (generation !== decodeGeneration.current || !formRef.current) return;
      const form = formRef.current;
      (form.elements.namedItem("device_serial") as HTMLInputElement).value = result.serial;
      (form.elements.namedItem("username") as HTMLInputElement).value = result.username;
      qrPayload.current = result.qr_payload;
    } catch {
      if (generation === decodeGeneration.current) setValidation("QR 이미지를 읽을 수 없습니다. 장치번호와 아이디를 직접 입력하세요.");
    } finally {
      if (generation === decodeGeneration.current) setReading(false);
    }
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || reading) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    const body = {
      alias: values.get("alias"),
      site: values.get("site"),
      store_ids: values.getAll("store_ids"),
      ...(connection
        ? { expected_generation: connection.generation }
        : { kind: values.get("kind") }),
      ...(!connection || replacement
        ? { username: values.get("username"), password: values.get("password") }
        : {}),
      ...(kind === "TVT_DEVICE" && (!connection || replacement)
        ? { device: { serial: values.get("device_serial"), country: values.get("device_country"), ...(qrPayload.current === undefined ? {} : { qr_payload: qrPayload.current }) } }
        : {}),
    };
    let parsed: unknown;
    try {
      parsed = parseConnectionBody(connection ? "patch" : "create", body);
    } catch {
      setValidation(
        "입력 내용을 확인하세요. 아이디와 비밀번호를 모두 입력해야 합니다.",
      );
      return;
    }
    setValidation("");
    // Credentials exist only for this one submission, never in browser storage.
    clearPrivate();
    await onSubmit(parsed);
  }
  return (
    <form
      ref={formRef}
      onSubmit={submit}
      className="wso-card mt-6 p-5 sm:p-6"
      autoComplete="off"
    >
      <h2 className="text-lg font-semibold">
        {connection ? "연결 수정" : "새 연결 등록"}
      </h2>
      <p className="mt-2 text-sm leading-6 text-[var(--wso-muted)]">
        계정 정보를 암호화해 저장합니다. 저장만으로 로그인이나 기기 연결이
        확인되지는 않습니다.
      </p>
      {validation && (
        <p role="alert" className="mt-4 text-[#A52A2A]">
          {validation}
        </p>
      )}
      <fieldset
        disabled={busy}
        className="mt-5 min-w-0 space-y-5 disabled:opacity-60"
      >
        {!connection && (
          <label className="block font-medium">
            연결 유형
            <select name="kind" className={inputClass} value={kind} onChange={event => { clearPrivate(); setValidation(""); setKind(event.target.value as typeof kind); }}>
              {connectionKinds.map((kind) => (
                <option key={kind} value={kind}>
                  {kindLabel[kind]}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="grid min-w-0 gap-5 md:grid-cols-2">
          <label className="block min-w-0 font-medium">
            연결 이름
            <input
              autoFocus
              name="alias"
              className={inputClass}
              defaultValue={connection?.alias}
              required
              maxLength={200}
            />
          </label>
          <label className="block min-w-0 font-medium">
            사이트 / 주소
            <input
              name="site"
              aria-label="사이트 / 주소"
              aria-describedby="connection-site-help"
              className={inputClass}
              defaultValue={connection?.site}
              required
              maxLength={500}
            />
            <span
              id="connection-site-help"
              className="mt-2 block text-xs font-normal text-[var(--wso-muted)]"
            >
              연결을 구분하는 주소 또는 위치를 입력하세요.
            </span>
          </label>
        </div>
        <fieldset className="min-w-0">
          <legend className="font-medium">매장 연결 · 선택 사항</legend>
          <p className="mt-2 text-xs text-[var(--wso-muted)]">
            여러 매장을 선택하거나 매장 없이 저장할 수 있습니다.
          </p>
          {stores.length ? (
            <div className="mt-3 grid gap-2 sm:grid-cols-2">
              {stores.map((store) => (
                <label
                  key={store.id}
                  className="flex min-w-0 items-center gap-3 rounded-lg border border-[var(--wso-border)] p-3"
                >
                  <input
                    type="checkbox"
                    name="store_ids"
                    value={store.id}
                    defaultChecked={connection?.store_ids.includes(store.id)}
                    onChange={clearPrivate}
                    className="h-4 w-4 shrink-0 accent-[#226594]"
                  />
                  <span className="break-words">{store.name}</span>
                </label>
              ))}
            </div>
          ) : (
            <p className="mt-3 rounded-lg bg-[var(--wso-bg)] p-3 text-sm">
              선택할 매장이 없습니다. 매장 없이 먼저 연결을 저장할 수 있습니다.
            </p>
          )}
        </fieldset>
        {connection && (
          <label className="flex items-center gap-3 font-medium">
            <input
              type="checkbox"
              checked={replacement}
              onChange={(event) => { clearPrivate(); setReplacement(event.target.checked); }}
              className="h-4 w-4 accent-[#226594]"
            />
            계정 정보 교체
          </label>
        )}
        {kind === "TVT_DEVICE" && (!connection || replacement) && (
          <div className="grid min-w-0 gap-5 md:grid-cols-2">
            <label className="block min-w-0 font-medium">장치번호
              <input name="device_serial" className={inputClass} required maxLength={63} autoComplete="off" spellCheck={false} />
            </label>
            <label className="block min-w-0 font-medium">국가
              <input name="device_country" aria-label="국가" className={inputClass} required minLength={2} maxLength={2} defaultValue="KR" autoComplete="off" spellCheck={false} aria-describedby="connection-country-help" />
              <span id="connection-country-help" className="mt-2 block text-xs font-normal text-[var(--wso-muted)]">국가 코드 두 글자를 입력하세요. 한국은 KR입니다.</span>
            </label>
            <label className="block min-w-0 font-medium md:col-span-2">QR 이미지 선택
              <input name="device_qr_image" aria-label="QR 이미지 선택" type="file" accept="image/png,image/jpeg,image/webp" className={inputClass} onChange={readQr} />
              <span className="mt-2 block text-xs font-normal text-[var(--wso-muted)]">이미지는 이 브라우저에서 읽습니다. 비밀번호는 직접 입력하세요.</span>
            </label>
            {reading && <p role="status" className="text-sm text-[var(--wso-muted)]">QR 이미지를 읽는 중…</p>}
          </div>
        )}
        {(!connection || replacement) && (
          <div className="grid min-w-0 gap-5 md:grid-cols-2">
            <label className="block min-w-0 font-medium">
              아이디
              <input
                name="username"
                className={inputClass}
                required
                maxLength={kind === "TVT_DEVICE" ? 63 : 512}
                autoComplete="off"
              />
            </label>
            <label className="block min-w-0 font-medium">
              비밀번호
              <input
                name="password"
                aria-label="비밀번호"
                aria-describedby="connection-password-help"
                type="password"
                className={inputClass}
                required
                maxLength={kind === "TVT_DEVICE" ? 63 : 4096}
                autoComplete="new-password"
              />
              <span
                id="connection-password-help"
                className="mt-2 block text-xs font-normal text-[var(--wso-muted)]"
              >
                저장된 비밀번호는 표시하지 않습니다.
              </span>
            </label>
          </div>
        )}
        <div className="flex flex-wrap gap-3 border-t border-[var(--wso-border)] pt-5">
          <button type="submit" className="wso-button-primary" disabled={reading}>
            {busy ? "저장 중…" : connection ? "변경 저장" : "연결 저장"}
          </button>
          <button
            type="button"
            onClick={() => { clearPrivate(); onCancel(); }}
            className="wso-button-secondary"
          >
            취소
          </button>
        </div>
      </fieldset>
    </form>
  );
}
