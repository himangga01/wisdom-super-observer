import { NextRequest, NextResponse } from "next/server";
import { CSRF_COOKIE, FLOW_COOKIE, SESSION_COOKIE, clearCookie, equalSecret, privateResponse, readAuthConfig } from "../../../../lib/auth";
export const runtime = "nodejs";
export async function GET() { return privateResponse(NextResponse.json({ error: "Use POST to sign out" }, { status: 405, headers: { Allow: "POST" } })); }
export async function POST(request: NextRequest) {
  try {
    const config = readAuthConfig();
    if (request.headers.get("origin") !== config.publicOrigin) return privateResponse(NextResponse.json({ error: "Request rejected" }, { status: 403 }));
    const csrf = request.cookies.get(CSRF_COOKIE)?.value ?? "";
    const session = request.cookies.get(SESSION_COOKIE)?.value;
    const submitted = request.headers.get("x-csrf-token") ?? String((await request.formData()).get("csrf_token") ?? "");
    if (!equalSecret(csrf, submitted) || !session) return privateResponse(NextResponse.json({ error: "Request rejected" }, { status: 403 }));
    const revoked = await fetch(`${config.apiOrigin}/api/v1/auth/session`, { method: "DELETE", headers: { Cookie: `${SESSION_COOKIE}=${session}`, Origin: config.publicOrigin, "X-CSRF-Token": csrf }, cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!revoked.ok && revoked.status !== 401) return privateResponse(NextResponse.json({ error: "Sign out unavailable. Please try again." }, { status: 503 }));
    const response = privateResponse(NextResponse.redirect(new URL("/?signed_out=1", config.publicOrigin), 303));
    for (const cookie of [SESSION_COOKIE, CSRF_COOKIE, FLOW_COOKIE]) clearCookie(response, cookie);
    response.headers.set("Clear-Site-Data", '"cache"');
    return response;
  } catch { return privateResponse(NextResponse.json({ error: "Sign out unavailable. Please try again." }, { status: 503 })); }
}
