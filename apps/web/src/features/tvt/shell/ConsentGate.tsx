import type { Consent, ConsentInput } from "../../../lib/tvt/api-client";
export function ConsentGate({ consent, busy, onDecision }: { consent: Consent; busy: boolean; onDecision: (body: ConsentInput) => void }) {
  if (consent.status === "accepted") return <p role="status" className="text-[var(--wso-success)]">현재 약관에 동의했습니다.</p>;
  return <section className="wso-card p-6" aria-labelledby="consent-title" aria-busy={busy}>
    <h2 id="consent-title" className="text-lg font-semibold">서비스 이용 동의</h2>
    <p className="mt-3 text-[var(--wso-muted)]">서비스 약관과 개인정보 처리방침을 확인하세요. 동의는 카메라나 마이크 사용 권한을 부여하지 않습니다.</p>
    <p className="mt-2 text-xs text-[var(--wso-muted)]">약관 버전: {consent.version}</p>
    <div className="my-4 flex flex-wrap gap-4"><a href={consent.terms.url} className="underline" target="_blank" rel="noopener noreferrer">서비스 약관</a><a href={consent.privacy.url} className="underline" target="_blank" rel="noopener noreferrer">개인정보 처리방침</a></div>
    {consent.status === "declined" && <p role="status" className="mb-4">동의를 거절했습니다. 설정을 확인할 수 있습니다.</p>}
    <div className="flex flex-wrap gap-3"><button className="wso-button-primary" disabled={busy} onClick={() => onDecision({ version: consent.version, decision: "accepted" })}>동의</button><button className="wso-button-secondary" disabled={busy || consent.status === "declined"} onClick={() => onDecision({ version: consent.version, decision: "declined" })}>거절</button></div>
  </section>;
}
