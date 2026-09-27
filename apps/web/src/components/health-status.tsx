export type HealthState = { status: "ok" } | { status: "unavailable" };

export function HealthStatus({ health }: { health: HealthState }) {
  const available = health.status === "ok";

  return (
    <p role="status" className="flex items-center gap-2 text-sm text-slate-600">
      <span
        aria-hidden="true"
        className={`size-2 rounded-full ${available ? "bg-emerald-600" : "bg-amber-600"}`}
      />
      {available ? "서비스 연결됨" : "서비스 연결 확인 불가"}
    </p>
  );
}
