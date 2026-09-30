/* eslint-disable @next/next/no-html-link-for-pages -- Full document navigation revalidates authorization and avoids personalized Router Cache. */
import type { ReactNode } from "react";
function Navigation({ signedIn }: { signedIn: boolean }) {
  return <nav aria-label="주 메뉴" className="space-y-1">
    <a href="/" className={`wso-nav-item ${!signedIn ? "wso-nav-active" : ""}`} aria-current={!signedIn ? "page" : undefined}><span aria-hidden="true">⌂</span> 서비스 홈</a>
    <a href="/stores" className={`wso-nav-item ${signedIn ? "wso-nav-active" : ""}`} aria-current={signedIn ? "page" : undefined}><span aria-hidden="true">▦</span> 내 매장</a>
  </nav>;
}
export function ServiceShell({ children, csrf }: { children: ReactNode; csrf?: string }) {
  const signedIn = csrf !== undefined;
  return <div className="wso-shell">
    <a className="wso-skip" href="#main">본문으로 이동</a>
    <aside className="wso-sidebar">
      <a href="/" className="wso-brand"><span className="wso-brand-icon" aria-hidden="true">W</span><span>Wisdom<span className="wso-brand-sub">Super Observer</span></span></a>
      <div className="px-3 py-6"><p className="mb-3 px-3 text-xs font-semibold tracking-wider text-[var(--wso-muted)]">작업 공간</p><Navigation signedIn={signedIn} /></div>
      <div className="mt-auto border-t border-[var(--wso-border)] p-6"><p className="text-xs text-[var(--wso-muted)]">Wisdom Super Observer</p><p className="mt-1 text-sm font-medium">매장을 더 가까이</p></div>
    </aside>
    <div className="wso-workspace">
      <header className="wso-header">
        <div className="flex min-w-0 items-center gap-3"><span aria-hidden="true" className="text-lg text-[var(--wso-muted)]">⌂</span><span className="text-sm font-medium">{signedIn ? "매장 관리 / 내 매장" : "서비스 홈"}</span></div>
        {signedIn ? <form method="post" action="/api/auth/logout"><input type="hidden" name="csrf_token" value={csrf} /><button className="wso-button-secondary" type="submit">로그아웃</button></form> : <a className="wso-button-secondary" href="/api/auth/login">로그인</a>}
      </header>
      <details className="wso-mobile-menu"><summary>메뉴</summary><div className="p-3"><Navigation signedIn={signedIn} /></div></details>
      <main id="main" className="wso-content">{children}</main>
    </div>
  </div>;
}
