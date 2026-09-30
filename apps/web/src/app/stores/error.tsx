/* eslint-disable @next/next/no-html-link-for-pages -- Full document navigation revalidates authorization and avoids personalized Router Cache. */
"use client";
export default function ErrorPage({ reset }: { reset: () => void }) { return <main className="mx-auto max-w-6xl p-10"><h1 className="text-2xl font-semibold">매장을 불러올 수 없습니다</h1><p role="alert" className="mt-3 text-slate-600">잠시 후 다시 시도하세요.</p><button onClick={reset} className="mt-6 rounded-lg bg-slate-900 px-5 py-3 text-white">다시 시도</button><a href="/" className="ml-6 underline">홈으로</a></main>; }
