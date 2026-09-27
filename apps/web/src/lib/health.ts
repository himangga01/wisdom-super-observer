import type { HealthState } from "../components/health-status";

type LiveHealthResponse = { status: "ok" };

export async function getLiveHealth(): Promise<HealthState> {
  const apiOrigin = process.env.API_INTERNAL_ORIGIN ?? "http://127.0.0.1:8000";

  try {
    const response = await fetch(new URL("/health/live", apiOrigin), {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return { status: "unavailable" };

    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "status" in payload &&
      payload.status === "ok"
    ) {
      const health: LiveHealthResponse = { status: "ok" };
      return health;
    }
  } catch {
    // A local API may not be running while the frontend is developed.
  }

  return { status: "unavailable" };
}
