/* eslint-disable @next/next/no-html-link-for-pages -- Full navigation refetches owner grants. */
export default function NotFound() {
  return (
    <div className="wso-card m-4 p-6 sm:m-6">
      <h1 className="text-2xl font-semibold">연결을 찾을 수 없습니다</h1>
      <p className="mt-3 text-[var(--wso-muted)]">
        이 연결을 열 수 없거나 연결이 존재하지 않습니다.
      </p>
      <a href="/connections" className="wso-button-secondary mt-5">
        연결 목록으로 이동
      </a>
    </div>
  );
}
