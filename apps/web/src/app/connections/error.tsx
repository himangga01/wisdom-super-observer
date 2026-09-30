/* eslint-disable @next/next/no-html-link-for-pages -- Full navigation refetches owner grants. */
"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="wso-card m-4 p-6 sm:m-6">
      <h1 className="text-2xl font-semibold">연결을 불러올 수 없습니다</h1>
      <p role="alert" className="mt-3 text-[var(--wso-muted)]">
        잠시 후 다시 시도하세요.
      </p>
      <button onClick={reset} className="wso-button-primary mt-5">
        다시 시도
      </button>
      <a href="/stores" className="wso-button-secondary ml-3 mt-5">
        내 매장으로 이동
      </a>
    </div>
  );
}
