import { HealthStatus } from "../components/health-status";
import { getLiveHealth } from "../lib/health";

export default async function HomePage() {
  const health = await getLiveHealth();

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col px-6 py-10 sm:px-10">
      <header className="border-b border-slate-200 pb-6">
        <p className="text-sm font-semibold tracking-wide text-slate-600">
          Wisdom Super Observer
        </p>
        <h1 className="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">
          서비스 작업 공간
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-6 text-slate-600">
          계정과 기기 기능을 위한 웹 서비스 기반을 준비하고 있습니다.
        </p>
      </header>
      <section aria-label="서비스 상태" className="mt-8">
        <h2 className="text-base font-semibold">API 상태</h2>
        <div className="mt-3 rounded-lg border border-slate-200 bg-white p-4">
          <HealthStatus health={health} />
        </div>
      </section>
    </main>
  );
}
