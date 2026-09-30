import { NextRequest, NextResponse } from "next/server";
import * as oidc from "openid-client";
import { FLOW_COOKIE, FLOW_SECONDS, authErrorResponse, encryptFlow, oidcConfiguration, privateResponse, readAuthConfig, safeReturnTo } from "../../../../lib/auth";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  try {
    const config = readAuthConfig();
    const client = await oidcConfiguration(config);
    const flow = { state: oidc.randomState(), nonce: oidc.randomNonce(), verifier: oidc.randomPKCECodeVerifier(), returnTo: safeReturnTo(request.nextUrl.searchParams.get("returnTo")), expires: Date.now() + FLOW_SECONDS * 1000 };
    const url = oidc.buildAuthorizationUrl(client, { redirect_uri: `${config.publicOrigin}/api/auth/callback`, scope: "openid", state: flow.state, nonce: flow.nonce, code_challenge: await oidc.calculatePKCECodeChallenge(flow.verifier), code_challenge_method: "S256" });
    const response = privateResponse(NextResponse.redirect(url));
    response.cookies.set(FLOW_COOKIE, encryptFlow(flow, config.flowKey), { secure: true, httpOnly: true, sameSite: "lax", path: "/", maxAge: FLOW_SECONDS });
    return response;
  } catch { return authErrorResponse(503); }
}
