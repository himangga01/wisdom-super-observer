import { NextRequest, NextResponse } from "next/server";
import * as oidc from "openid-client";
import { CSRF_COOKIE, FLOW_COOKIE, SESSION_COOKIE, authErrorResponse, clearCookie, decryptFlow, oidcConfiguration, privateResponse, readAuthConfig } from "../../../../lib/auth";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  let response: NextResponse;
  try {
    const config = readAuthConfig();
    const flow = decryptFlow(request.cookies.get(FLOW_COOKIE)?.value ?? "", config.flowKey);
    const callback = new URL(`${config.publicOrigin}/api/auth/callback`);
    callback.search = request.nextUrl.search;
    const client = await oidcConfiguration(config);
    const tokens = await oidc.authorizationCodeGrant(client, callback, { pkceCodeVerifier: flow.verifier, expectedState: flow.state, expectedNonce: flow.nonce, idTokenExpected: true });
    if (!tokens.id_token) throw new Error("Missing identity token");
    const exchange = await fetch(`${config.apiOrigin}/api/v1/auth/sessions`, { method: "POST", headers: { "Content-Type": "application/json", "X-WSO-Auth-Key": config.exchangeKey }, body: JSON.stringify({ id_token: tokens.id_token, nonce: flow.nonce }), cache: "no-store", signal: AbortSignal.timeout(10_000) });
    if (!exchange.ok) throw new Error("Exchange failed");
    const session = await exchange.json() as { session_id: string; csrf_token: string; expires_at: string };
    const expires = new Date(session.expires_at);
    if (![session.session_id, session.csrf_token].every(v => typeof v === "string" && /^[A-Za-z0-9_-]+$/.test(v)) || !Number.isFinite(expires.getTime()) || expires.getTime() <= Date.now()) throw new Error("Invalid session");
    response = privateResponse(NextResponse.redirect(new URL(flow.returnTo, config.publicOrigin), 303));
    response.cookies.set(SESSION_COOKIE, session.session_id, { secure: true, httpOnly: true, sameSite: "lax", path: "/", expires });
    response.cookies.set(CSRF_COOKIE, session.csrf_token, { secure: true, httpOnly: false, sameSite: "strict", path: "/", expires });
  } catch {
    // Return a generic local error; never reflect provider error descriptions or tokens.
    response = authErrorResponse(400);
  }
  clearCookie(response, FLOW_COOKIE);
  return response;
}
