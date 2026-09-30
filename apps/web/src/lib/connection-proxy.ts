import "server-only";
import { NextRequest, NextResponse } from "next/server";
import {
  CSRF_COOKIE,
  SESSION_COOKIE,
  equalSecret,
  privateResponse,
  readAuthConfig,
} from "./auth";
import {
  connectionMessage,
  parseConnectionBody,
  publicConnection,
  uuid,
} from "./connections";
function fail(status: number) {
  return privateResponse(
    NextResponse.json({ error: connectionMessage(status) }, { status }),
  );
}
export async function proxyConnection(
  request: NextRequest,
  segments: string[],
) {
  try {
    const tenant = request.nextUrl.searchParams.get("tenant_id");
    if (
      !uuid.safeParse(tenant).success ||
      request.nextUrl.searchParams.size !== 1 ||
      segments.length > 2 ||
      (segments.length && !uuid.safeParse(segments[0]).success) ||
      (segments.length === 2 && segments[1] !== "disconnect")
    )
      return fail(404);
    const method = request.method;
    const allowed =
      segments.length === 0
        ? ["GET", "POST"]
        : segments.length === 1
          ? ["GET", "PATCH", "DELETE"]
          : ["POST"];
    if (!allowed.includes(method)) return fail(405);
    const config = readAuthConfig();
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    if (!session) return fail(401);
    let payload: unknown;
    const csrf = request.cookies.get(CSRF_COOKIE)?.value ?? "";
    if (method !== "GET") {
      if (
        request.headers.get("origin") !== config.publicOrigin ||
        !equalSecret(csrf, request.headers.get("x-csrf-token") ?? "")
      )
        return fail(403);
      if (!request.headers.get("content-type")?.startsWith("application/json"))
        return fail(422);
      try {
        const raw = await request.text();
        if (raw.length > 24_000) return fail(422);
        payload = parseConnectionBody(
          segments.length === 0
            ? "create"
            : method === "PATCH"
              ? "patch"
              : "revoke",
          JSON.parse(raw),
        );
      } catch {
        return fail(422);
      }
    }
    const response = await fetch(
      `${config.apiOrigin}/api/v1/connections${segments.length ? "/" + segments.join("/") : ""}?tenant_id=${tenant}`,
      {
        method,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10_000),
        headers: {
          Cookie: `${SESSION_COOKIE}=${session}`,
          ...(method === "GET"
            ? {}
            : {
                Origin: config.publicOrigin,
                "X-CSRF-Token": csrf,
                "Content-Type": "application/json",
              }),
        },
        ...(method === "GET" ? {} : { body: JSON.stringify(payload) }),
      },
    );
    if (!response.ok)
      return fail(
        [401, 403, 404, 409, 422, 503].includes(response.status)
          ? response.status
          : 503,
      );
    if (response.status === 204 && method === "DELETE")
      return privateResponse(new NextResponse(null, { status: 204 }));
    const data = await response.json();
    const result =
      method === "GET" && segments.length === 0
        ? {
            items: (data.items as unknown[]).map(publicConnection),
            selected_tenant_id: tenant,
          }
        : publicConnection(data);
    if (
      ("items" in result ? result.items : [result]).some(
        (item) => item.tenant_id !== tenant,
      )
    )
      return fail(503);
    return privateResponse(
      NextResponse.json(result, { status: response.status }),
    );
  } catch {
    return fail(503);
  }
}
