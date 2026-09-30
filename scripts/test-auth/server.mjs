// Test-only signed OIDC issuer, API contract fixture and HTTPS Next launcher.
import { createServer as httpsServer } from "node:https";
import { createServer as httpServer } from "node:http";
import {
  generateKeyPairSync,
  randomBytes,
  createHash,
  sign,
  verify,
} from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { spawn, spawnSync } from "node:child_process";
const root = fileURLToPath(new URL("../../", import.meta.url));
const certDir = resolve(root, "auth-state/https-test");
const python =
  process.env.WSO_TEST_PYTHON || resolve(root, ".venv/Scripts/python.exe");
const certificates = spawnSync(
  python,
  [resolve(root, "scripts/test-auth/certificates.py")],
  { stdio: "inherit" },
);
if (certificates.status !== 0)
  throw new Error("Test certificate generation failed");
const issuer = "https://localhost:9443";
const origin = "https://localhost:3443";
const secret = "test-only-client-secret";
const exchangeKey = "test-only-exchange-key-at-least-32-characters";
const { privateKey, publicKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
});
const jwk = {
  ...publicKey.export({ format: "jwk" }),
  kid: "test-key",
  use: "sig",
  alg: "RS256",
};
const tenantA = "10000000-0000-4000-8000-000000000001";
const tenantB = "10000000-0000-4000-8000-000000000002";
const storeA = {
  id: "20000000-0000-4000-8000-000000000001",
  tenant_id: tenantA,
  name: "강남점",
  timezone: "Asia/Seoul",
  active: true,
};
const storeB = {
  ...storeA,
  id: "20000000-0000-4000-8000-000000000002",
  name: "홍대점",
};
const storeC = {
  ...storeA,
  id: "20000000-0000-4000-8000-000000000003",
  tenant_id: tenantB,
  name: "부산점",
};
const profiles = {
  single: {
    memberships: [{ tenant_id: tenantA, role: "OWNER" }],
    stores: [storeA],
  },
  multi: {
    memberships: [
      { tenant_id: tenantA, role: "OWNER" },
      { tenant_id: tenantB, role: "OWNER" },
    ],
    stores: [storeA, storeB, storeC],
  },
  staff: {
    memberships: [{ tenant_id: tenantA, role: "STAFF" }],
    stores: [storeA],
  },
  ownerempty: {
    memberships: [{ tenant_id: tenantA, role: "OWNER" }],
    stores: [],
  },
  empty: { memberships: [], stores: [] },
};
const codes = new Map();
const sessions = new Map();
const nonces = new Set();
let failStores = false;
let tokenMode = "valid";
const connections = new Map();
let failConnections = 0;
let conflict = false;
let connectionWrites = 0;
function json(res, status, data) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Cache-Control": "private, no-store",
  });
  res.end(JSON.stringify(data));
}
async function body(req) {
  let value = "";
  for await (const chunk of req) value += chunk;
  return value;
}
function token(payload) {
  const header = Buffer.from(
    JSON.stringify({ alg: "RS256", kid: "test-key", typ: "JWT" }),
  ).toString("base64url");
  const claims = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signing = header + "." + claims;
  return (
    signing +
    "." +
    sign("RSA-SHA256", Buffer.from(signing), privateKey).toString("base64url")
  );
}
httpsServer(
  {
    key: readFileSync(resolve(certDir, "server-key.pem")),
    cert: readFileSync(resolve(certDir, "server.pem")),
  },
  async (req, res) => {
    try {
      const url = new URL(req.url, issuer);
      if (url.pathname === "/.well-known/openid-configuration")
        return json(res, 200, {
          issuer,
          authorization_endpoint: issuer + "/authorize",
          token_endpoint: issuer + "/token",
          jwks_uri: issuer + "/jwks",
          response_types_supported: ["code"],
          subject_types_supported: ["public"],
          id_token_signing_alg_values_supported: ["RS256"],
          token_endpoint_auth_methods_supported: ["client_secret_post"],
          code_challenge_methods_supported: ["S256"],
        });
      if (url.pathname === "/jwks") return json(res, 200, { keys: [jwk] });
      if (url.pathname === "/authorize") {
        if (
          url.searchParams.get("redirect_uri") !==
            origin + "/api/auth/callback" ||
          url.searchParams.get("client_id") !== "test-web" ||
          url.searchParams.get("code_challenge_method") !== "S256"
        )
          return json(res, 400, {});
        const profile = url.searchParams.get("profile");
        if (!profile) {
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(
            "<html><body><h1>Test identity provider</h1>" +
              Object.keys(profiles)
                .map(
                  (name) =>
                    '<form method="get"><input type="hidden" name="profile" value="' +
                    name +
                    '">' +
                    [...url.searchParams]
                      .map(
                        ([key, value]) =>
                          '<input type="hidden" name="' +
                          key +
                          '" value="' +
                          value
                            .replaceAll("&", "&amp;")
                            .replaceAll('"', "&quot;") +
                          '">',
                      )
                      .join("") +
                    "<button>" +
                    name +
                    "</button></form>",
                )
                .join("") +
              "</body></html>",
          );
          return;
        }
        if (!profiles[profile]) return json(res, 400, {});
        const code = randomBytes(24).toString("base64url");
        codes.set(code, {
          profile,
          nonce: url.searchParams.get("nonce"),
          challenge: url.searchParams.get("code_challenge"),
          redirect: url.searchParams.get("redirect_uri"),
        });
        const callback = new URL(origin + "/api/auth/callback");
        callback.searchParams.set("code", code);
        callback.searchParams.set("state", url.searchParams.get("state"));
        callback.searchParams.set("iss", issuer);
        res.writeHead(302, { Location: callback.href });
        res.end();
        return;
      }
      if (url.pathname === "/token" && req.method === "POST") {
        const params = new URLSearchParams(await body(req));
        const code = codes.get(params.get("code"));
        codes.delete(params.get("code"));
        if (
          !code ||
          params.get("client_id") !== "test-web" ||
          params.get("client_secret") !== secret ||
          params.get("redirect_uri") !== code.redirect ||
          createHash("sha256")
            .update(params.get("code_verifier") || "")
            .digest("base64url") !== code.challenge
        )
          return json(res, 400, { error: "invalid_grant" });
        const now = Math.floor(Date.now() / 1000);
        const claims = {
          iss: tokenMode === "issuer" ? "https://wrong-issuer.invalid" : issuer,
          aud: tokenMode === "audience" ? "wrong-client" : "test-web",
          sub: code.profile,
          nonce: tokenMode === "nonce" ? "wrong-nonce" : code.nonce,
          iat: now,
          exp: tokenMode === "expired" ? now - 120 : now + 300,
        };
        let idToken = token(claims);
        if (tokenMode === "signature") {
          const parts = idToken.split(".");
          const signature = Buffer.from(parts[2], "base64url");
          signature[0] ^= 1;
          idToken =
            parts[0] + "." + parts[1] + "." + signature.toString("base64url");
        }
        return json(res, 200, {
          access_token: randomBytes(24).toString("base64url"),
          token_type: "Bearer",
          expires_in: 300,
          id_token: idToken,
        });
      }
      json(res, 404, {});
    } catch {
      json(res, 500, {});
    }
  },
).listen(9443, "localhost");
httpServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://127.0.0.1:9100");
    if (url.pathname === "/__test/token-mode") {
      tokenMode = url.searchParams.get("value");
      return json(res, 200, {});
    }
    if (url.pathname === "/__test/health")
      return json(res, 200, { ready: true });
    if (url.pathname === "/__test/reset") {
      sessions.clear();
      nonces.clear();
      connections.clear();
      failConnections = 0;
      conflict = false;
      connectionWrites = 0;
      failStores = false;
      tokenMode = "valid";
      return json(res, 200, {});
    }
    if (url.pathname === "/__test/fail-connections") {
      failConnections = Number(url.searchParams.get("status") || 503);
      return json(res, 200, {});
    }
    if (url.pathname === "/__test/conflict") {
      conflict = true;
      return json(res, 200, {});
    }
    if (url.pathname === "/__test/connection-stats")
      return json(res, 200, { writes: connectionWrites });
    if (url.pathname === "/__test/expire") {
      for (const session of sessions.values())
        session.expires_at = new Date(0).toISOString();
      return json(res, 200, {});
    }
    if (url.pathname === "/__test/fail-stores") {
      failStores = true;
      return json(res, 200, {});
    }
    if (url.pathname === "/api/v1/auth/sessions" && req.method === "POST") {
      if (req.headers["x-wso-auth-key"] !== exchangeKey)
        return json(res, 403, {});
      const submitted = JSON.parse(await body(req));
      const parts = submitted.id_token.split(".");
      if (
        parts.length !== 3 ||
        !verify(
          "RSA-SHA256",
          Buffer.from(parts[0] + "." + parts[1]),
          publicKey,
          Buffer.from(parts[2], "base64url"),
        )
      )
        return json(res, 401, {});
      const claims = JSON.parse(Buffer.from(parts[1], "base64url"));
      if (
        claims.iss !== issuer ||
        claims.aud !== "test-web" ||
        claims.nonce !== submitted.nonce ||
        claims.exp <= Date.now() / 1000 ||
        !profiles[claims.sub] ||
        nonces.has(claims.nonce)
      )
        return json(res, 401, {});
      nonces.add(claims.nonce);
      const session_id = randomBytes(32).toString("base64url");
      const csrf_token = randomBytes(32).toString("base64url");
      const session = {
        ...profiles[claims.sub],
        user_id: "40000000-0000-4000-8000-000000000001",
        expires_at: new Date(claims.exp * 1000).toISOString(),
        csrf_token,
      };
      sessions.set(session_id, session);
      return json(res, 200, {
        session_id,
        csrf_token,
        expires_at: session.expires_at,
      });
    }
    const id = /(?:^|;\s*)__Host-wso-session=([^;]+)/.exec(
      req.headers.cookie || "",
    )?.[1];
    const session = sessions.get(id);
    if (!session || Date.parse(session.expires_at) <= Date.now())
      return json(res, 401, {});
    if (url.pathname === "/api/v1/me")
      return json(res, 200, {
        user_id: session.user_id,
        memberships: session.memberships,
        expires_at: session.expires_at,
      });
    if (url.pathname === "/api/v1/auth/session" && req.method === "DELETE") {
      if (
        req.headers.origin !== origin ||
        req.headers["x-csrf-token"] !== session.csrf_token
      )
        return json(res, 403, {});
      sessions.delete(id);
      res.writeHead(204);
      res.end();
      return;
    }
    const tenant = url.searchParams.get("tenant_id");
    if (
      !session.memberships.some((membership) => membership.tenant_id === tenant)
    )
      return json(res, 404, {});
    if (failStores) return json(res, 503, {});
    const allowed = session.stores.filter(
      (store) => store.tenant_id === tenant,
    );
    if (
      url.pathname === "/api/v1/connections" ||
      url.pathname.startsWith("/api/v1/connections/")
    ) {
      if (
        !session.memberships.some(
          (membership) =>
            membership.tenant_id === tenant && membership.role === "OWNER",
        )
      )
        return json(res, 403, {});
      if (
        req.method !== "GET" &&
        (req.headers.origin !== origin ||
          req.headers["x-csrf-token"] !== session.csrf_token)
      )
        return json(res, 403, {});
      if (failConnections)
        return json(res, failConnections, { detail: "fixture-private-detail" });
      const parts = url.pathname
        .slice("/api/v1/connections".length)
        .split("/")
        .filter(Boolean);
      if (req.method === "GET" && parts.length === 0)
        return json(res, 200, {
          items: [...connections.values()].filter(
            (item) => item.tenant_id === tenant,
          ),
          selected_tenant_id: tenant,
        });
      const item = connections.get(parts[0]);
      if (parts.length && (!item || item.tenant_id !== tenant))
        return json(res, 404, {});
      if (req.method === "GET") return json(res, 200, item);
      connectionWrites++;
      const submitted = JSON.parse(await body(req));
      if (
        submitted.store_ids?.some(
          (id) => !allowed.some((store) => store.id === id),
        )
      )
        return json(res, 404, {});
      if (req.method === "POST" && parts.length === 0) {
        if (
          !["TVT_ACCOUNT", "TVT_DEVICE", "TYCO_ACCOUNT"].includes(
            submitted.kind,
          ) ||
          !submitted.alias?.trim() ||
          !submitted.site?.trim() ||
          !submitted.username?.trim() ||
          !submitted.password?.trim()
        )
          return json(res, 422, {});
        const connection = {
          id:
            "30000000-0000-4000-8000-" +
            String(connections.size + 1).padStart(12, "0"),
          tenant_id: tenant,
          kind: submitted.kind,
          alias: submitted.alias,
          site: submitted.site,
          status: "NOT_VERIFIED",
          last_success: null,
          generation: 1,
          store_ids: submitted.store_ids ?? [],
        };
        connections.set(connection.id, connection);
        return json(res, 201, connection);
      }
      if (conflict) {
        item.generation++;
        item.alias = "다른 곳에서 변경";
        conflict = false;
      }
      if (submitted.expected_generation !== item.generation)
        return json(res, 409, {});
      if (req.method === "DELETE") {
        connections.delete(item.id);
        res.writeHead(204);
        res.end();
        return;
      }
      item.generation++;
      if (parts[1] === "disconnect") item.status = "DISCONNECTED";
      else {
        if (submitted.alias !== undefined) item.alias = submitted.alias;
        if (submitted.site !== undefined) item.site = submitted.site;
        if (submitted.store_ids !== undefined)
          item.store_ids = submitted.store_ids;
        if (
          submitted.username !== undefined &&
          submitted.password !== undefined
        )
          item.status = "NOT_VERIFIED";
      }
      return json(res, 200, item);
    }
    if (url.pathname === "/api/v1/stores")
      return json(res, 200, { items: allowed, selected_tenant_id: tenant });
    if (url.pathname.startsWith("/api/v1/stores/")) {
      const store = allowed.find(
        (store) => store.id === url.pathname.split("/").at(-1),
      );
      return json(res, store ? 200 : 404, store || {});
    }
    json(res, 404, {});
  } catch {
    json(res, 500, {});
  }
}).listen(9100, "127.0.0.1");
const next = spawn(
  process.execPath,
  [
    resolve(root, "apps/web/node_modules/next/dist/bin/next"),
    "dev",
    "--hostname",
    "localhost",
    "--port",
    "3443",
    "--experimental-https",
    "--experimental-https-key",
    resolve(certDir, "server-key.pem"),
    "--experimental-https-cert",
    resolve(certDir, "server.pem"),
    "--experimental-https-ca",
    resolve(certDir, "ca.pem"),
  ],
  {
    cwd: resolve(root, "apps/web"),
    stdio: "inherit",
    env: {
      ...process.env,
      NODE_EXTRA_CA_CERTS: resolve(certDir, "ca.pem"),
      WSO_PUBLIC_ORIGIN: origin,
      WSO_OIDC_ISSUER: issuer,
      WSO_OIDC_CLIENT_ID: "test-web",
      WSO_OIDC_CLIENT_SECRET: secret,
      WSO_AUTH_EXCHANGE_KEY: exchangeKey,
      WSO_FLOW_ENCRYPTION_KEY: randomBytes(32).toString("base64url"),
      API_INTERNAL_ORIGIN: "http://127.0.0.1:9100",
    },
  },
);
function stop() {
  next.kill();
  process.exit();
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
next.on("exit", (code) => process.exit(code ?? 1));
