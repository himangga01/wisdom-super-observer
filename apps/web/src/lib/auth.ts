import "server-only";
import { createCipheriv, createDecipheriv, randomBytes, timingSafeEqual } from "node:crypto";
import * as oidc from "openid-client";
import { NextResponse } from "next/server";

export const SESSION_COOKIE = "__Host-wso-session";
export const CSRF_COOKIE = "__Host-wso-csrf";
export const FLOW_COOKIE = "__Host-wso-flow";
export const FLOW_SECONDS = 300;
export type Flow = { state: string; nonce: string; verifier: string; returnTo: string; expires: number };

export function readAuthConfig(env: Record<string, string | undefined> = process.env) {
  function required(name: string) { const value = env[name]; if (!value) throw new Error("Authentication configuration unavailable"); return value; }
  function url(name: string, loopback = false) {
    const value = new URL(required(name));
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(value.hostname);
    if ((value.protocol !== "https:" && !(loopback && local && value.protocol === "http:")) || value.username || value.password || value.search || value.hash || (name !== "WSO_OIDC_ISSUER" && value.pathname !== "/")) throw new Error("Invalid authentication origin");
    return value;
  }
  const keyValue = required("WSO_FLOW_ENCRYPTION_KEY");
  const flowKey = Buffer.from(keyValue, "base64url");
  if (flowKey.length !== 32 || flowKey.toString("base64url") !== keyValue || keyValue === env.WSO_AUTH_EXCHANGE_KEY || keyValue === env.WSO_OIDC_CLIENT_SECRET) throw new Error("Invalid flow encryption key");
  return { publicOrigin: url("WSO_PUBLIC_ORIGIN").origin, issuer: url("WSO_OIDC_ISSUER"), apiOrigin: url("API_INTERNAL_ORIGIN", true).origin, clientId: required("WSO_OIDC_CLIENT_ID"), clientSecret: required("WSO_OIDC_CLIENT_SECRET"), exchangeKey: required("WSO_AUTH_EXCHANGE_KEY"), flowKey };
}

export function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020]/.test(value)) return "/stores";
  try {
    const url = new URL(value, "https://local.invalid");
    if (url.origin !== "https://local.invalid" || !/^\/stores(?:\/[0-9a-f-]{36})?\/?$/.test(url.pathname)) return "/stores";
    return url.pathname + url.search;
  } catch { return "/stores"; }
}
export function encryptFlow(flow: Flow, key: Buffer) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(FLOW_COOKIE));
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(flow), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString("base64url");
}
export function decryptFlow(value: string, key: Buffer): Flow {
  if (value.length > 4096) throw new Error("Invalid flow");
  const bytes = Buffer.from(value, "base64url");
  if (bytes.length < 29 || bytes.toString("base64url") !== value) throw new Error("Invalid flow");
  const decipher = createDecipheriv("aes-256-gcm", key, bytes.subarray(0, 12));
  decipher.setAAD(Buffer.from(FLOW_COOKIE));
  decipher.setAuthTag(bytes.subarray(12, 28));
  const flow: Flow = JSON.parse(Buffer.concat([decipher.update(bytes.subarray(28)), decipher.final()]).toString("utf8"));
  if (![flow.state, flow.nonce, flow.verifier].every(v => typeof v === "string" && v.length > 0) || !Number.isFinite(flow.expires) || flow.expires <= Date.now() || flow.expires > Date.now() + FLOW_SECONDS * 1000 || safeReturnTo(flow.returnTo) !== flow.returnTo) throw new Error("Invalid flow");
  return flow;
}
export function equalSecret(a: string, b: string) {
  const left = Buffer.from(a); const right = Buffer.from(b);
  return left.length > 0 && left.length === right.length && timingSafeEqual(left, right);
}
export async function oidcConfiguration(config: ReturnType<typeof readAuthConfig>) {
  const client = await oidc.discovery(config.issuer, config.clientId, { client_secret: config.clientSecret, id_token_signed_response_alg: "RS256" }, oidc.ClientSecretPost(config.clientSecret));
  // Validate the ID token signature as well as protocol claims in the browser backend.
  oidc.enableNonRepudiationChecks(client);
  return client;
}
export function privateResponse(response: NextResponse) {
  response.headers.set("Cache-Control", "private, no-store, max-age=0");
  response.headers.set("Referrer-Policy", "no-referrer");
  return response;
}
export function clearCookie(response: NextResponse, name: string) {
  response.cookies.set(name, "", { secure: true, httpOnly: name !== CSRF_COOKIE, sameSite: name === CSRF_COOKIE ? "strict" : "lax", path: "/", maxAge: 0 });
}
export function authErrorResponse(status: number) {
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>로그인을 완료할 수 없습니다 · Wisdom</title><style>body{margin:0;background:#F7F8FA;color:#1C1C1E;font:14px Arial,"Malgun Gothic",sans-serif}main{max-width:480px;margin:12vh auto;padding:32px;background:white;border:1px solid #E7EAEE;border-radius:14px}p{color:#626973;line-height:1.8}h1{font-size:24px}a{display:inline-block;padding:12px 16px;border-radius:8px;background:#1C1C1E;color:white;text-decoration:none;margin:16px 12px 0 0}a:last-child{background:#DCEAFA;color:#1C1C1E}a:focus-visible{outline:2px solid #226594;outline-offset:4px}@media(max-width:600px){main{margin:24px 16px;padding:24px}}</style></head><body><main><p>Wisdom Super Observer</p><h1>요청을 완료할 수 없습니다</h1><p role="alert">인증 정보가 만료되었거나 요청을 확인할 수 없습니다. 로그인부터 다시 시작하세요.</p><a href="/api/auth/login">다시 로그인</a><a href="/">홈으로 이동</a></main></body></html>`;
  return privateResponse(new NextResponse(html, { status, headers: { "Content-Type": "text/html; charset=utf-8" } }));
}
