// Test-only coordinator. No account/API responses are manufactured here.
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, existsSync, statSync, writeFileSync, mkdirSync } from "node:fs";
import { createServer, request } from "node:https";
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomBytes, randomUUID } from "node:crypto";

const root = fileURLToPath(new URL("../../", import.meta.url));
const stateFile = process.env.WSO_TVT_ACCOUNT_BROWSER_STATE_FILE;
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
function state() {
  if (!stateFile || !existsSync(stateFile) || statSync(stateFile).size > 65536)
    throw new Error("Private fixture state unavailable");
  const value = JSON.parse(readFileSync(stateFile, "utf8"));
  if (value.proofKind !== "actual-pg-rpc-https" || value.baseURL !== "https://localhost:3543")
    throw new Error("Private fixture state rejected");
  return value;
}
function cleanEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    !/^(WSO_|PG|DATABASE|NODE_)/.test(key) && !["SSL_CERT_FILE", "SSL_CERT_DIR"].includes(key)));
}
export function directoryAuthEnvironment(context, env = process.env) {
  const mode = env.WSO_TEST_DIRECTORY_BROWSER;
  if (mode === undefined && context.directoryMode === undefined) return {};
  if (mode !== "1" || context.directoryMode !== true) throw new Error("Explicit directory mode mismatch");
  const auth = context.nextAuth;
  const keys = ["WSO_OIDC_ISSUER", "WSO_OIDC_CLIENT_ID", "WSO_OIDC_CLIENT_SECRET", "WSO_AUTH_EXCHANGE_KEY", "WSO_FLOW_ENCRYPTION_KEY"];
  if (!auth || typeof auth !== "object" || Object.keys(auth).sort().join() !== keys.sort().join()) throw new Error("Private directory auth rejected");
  const issuer = new URL(auth.WSO_OIDC_ISSUER);
  if (issuer.protocol !== "https:" || issuer.hostname !== "localhost" || !issuer.port || issuer.username || issuer.password || issuer.pathname !== "/" || issuer.search || issuer.hash || issuer.origin !== auth.WSO_OIDC_ISSUER || auth.WSO_OIDC_CLIENT_ID !== "fixture-web") throw new Error("Private directory issuer rejected");
  for (const key of keys.slice().filter(key => !["WSO_OIDC_ISSUER", "WSO_OIDC_CLIENT_ID"].includes(key))) {
    if (typeof auth[key] !== "string" || !/^[A-Za-z0-9_-]{43,128}$/.test(auth[key])) throw new Error("Private directory credential rejected");
  }
  const flow = Buffer.from(auth.WSO_FLOW_ENCRYPTION_KEY, "base64url");
  if (flow.length !== 32 || flow.toString("base64url") !== auth.WSO_FLOW_ENCRYPTION_KEY || new Set(keys.filter(key => key.endsWith("KEY") || key.endsWith("SECRET")).map(key => auth[key])).size !== 3) throw new Error("Private directory credential rejected");
  return { ...auth };
}
function evidenceDirectory() {
  return resolve(root, ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan", process.env.WSO_TEST_DIRECTORY_BROWSER === "1" ? "W07-directory-browser-runtime-evidence" : "W05-account-browser-fixture-fix1-evidence");
}
async function health(url, ca) {
  return new Promise((done) => {
    const call = request(url, { ca, timeout: 1000, rejectUnauthorized: true }, (response) => {
      response.resume(); done(response.statusCode === 200);
    });
    call.on("timeout", () => call.destroy());
    call.on("error", () => done(false));
    call.end();
  });
}
// One reporting deadline, nested budgets, and a separate outer observer margin.
// A resource owner is NEVER terminated at the reporting deadline: custody stays
// with this coordinator until its original child handle actually settles.
const running = child => Boolean(child && child.exitCode === null && child.signalCode == null);
export const CLEANUP = Object.freeze({ nextMs: 20000, runtimeMs: 100000, coordinatorMs: 120000, setupMs: 130000 });
export async function stopOwned(child, { deadline, resourceOwner = false, now = () => performance.now(), pause: wait = pause } = {}) {
  if (!child) return;
  if (running(child)) {
    child.stdin.once?.("error", () => {}); // A concurrent owned exit must not kill this custodian.
    child.stdin.end("close\n");
    const graceful = resourceOwner ? deadline : Math.max(now(), deadline - 5000);
    while (running(child) && now() < graceful) await wait(50);
    if (running(child) && !resourceOwner) {
      child.kill(); // Exact owned Next handle only; it owns no fixture DB/key custody.
      while (running(child) && now() < deadline) await wait(50);
    }
    if (running(child)) {
      const error = new Error("Owned cleanup deadline exceeded; custody retained");
      error.custodyRetained = true;
      throw error;
    }
  }
  if (child.exitCode !== 0) throw new Error("Owned child exited abnormally");
}
export async function retainCustody(child, { pause: wait = pause } = {}) {
  // No PID lookup, process-tree kill, timeout reset, or detachment. The original
  // process handle and stdin remain owned until nested finally blocks finish.
  while (child && running(child)) await wait(50);
}
async function nextProcess() {
  const context = state();
  const { default: next } = await import(pathToFileURL(resolve(root, "apps/web/node_modules/next/dist/server/next.js")).href);
  const app = next({ dev: true, dir: resolve(root, "apps/web"), hostname: "localhost", port: 3543 });
  await app.prepare();
  const handler = app.getRequestHandler();
  const server = createServer({ key: readFileSync(context.keyFile), cert: readFileSync(context.certificateFile) }, (req, res) => handler(req, res));
  server.on("error", () => process.exit(1));
  server.listen(3543, "localhost");
  let stopping = false;
  async function close() {
    if (stopping) return;
    stopping = true;
    server.close(); server.closeAllConnections();
    await app.close();
    process.exit(0);
  }
  process.stdin.once("data", close);
  process.stdin.once("end", close);
}
async function coordinator() {
  if (process.env.WSO_TEST_ACCOUNT_BROWSER !== "1" || !stateFile)
    throw new Error("Explicit browser fixture activation required");
  const python = process.env.WSO_TEST_PYTHON || resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  // Resolve the trusted base executable and venv site before spawning, avoiding
  // the Windows venv redirector's intermediate PID.
  const inspected = spawnSync(python, ["-c", "import json,sys,sysconfig;print(json.dumps([sys._base_executable,sysconfig.get_paths()['purelib'],sys.prefix]))"], { encoding: "utf8", windowsHide: true, timeout: 5000 });
  if (inspected.status !== 0) throw new Error("Trusted Python unavailable");
  const [base, site, prefix] = JSON.parse(inspected.stdout);
  const launch = `import site,runpy,sys;sys.prefix=${JSON.stringify(prefix)};site.addsitedir(${JSON.stringify(site)});sys.path.insert(0,${JSON.stringify(root)});runpy.run_path(${JSON.stringify(resolve(root, "scripts/test-tvt-account/runtime.py"))},run_name='__main__')`;
  let runtime, web;
  let stopping;
  const owner = randomBytes(16).toString("hex");
  const shutdown = () => stopping ??= (async () => {
    const started = performance.now();
    const deadline = started + CLEANUP.coordinatorMs;
    const evidence = evidenceDirectory();
    mkdirSync(evidence, { recursive: true });
    const events = [];
    const receipt = (failureReported) => {
      const snapshot = { coordinatorPid: process.pid, runtimePid: runtime?.pid ?? null, runtimeExitCode: runtime?.exitCode ?? null, runtimeSignal: runtime?.signalCode ?? null, nextPid: web?.pid ?? null, nextExitCode: web?.exitCode ?? null, nextSignal: web?.signalCode ?? null, stateRemoved: !existsSync(stateFile), cleanupDeadlineMs: CLEANUP.coordinatorMs, elapsedMs: performance.now() - started, failureReported, incomplete: existsSync(stateFile) || [web, runtime].some(child => child && running(child)), custodyRetained: [web, runtime].some(child => child && running(child)) };
      events.push(snapshot);
      writeFileSync(resolve(evidence, `coordinator-resources-${owner}.json`), JSON.stringify({ ...snapshot, events }, null, 2) + "\n");
    };
    let failure;
    try {
      try { await stopOwned(web, { deadline: Math.min(deadline, started + CLEANUP.nextMs) }); }
      catch (error) { failure = error; receipt(true); }
      try { await stopOwned(runtime, { deadline: Math.min(deadline, performance.now() + CLEANUP.runtimeMs), resourceOwner: true }); }
      catch (error) { failure ??= error; receipt(true); }
      // On an overrun keep this custodian alive, publishing incomplete status
      // before waiting. The outer observer may fail; it must never kill us.
      if ([web, runtime].some(child => child && running(child))) {
        receipt(true);
        await Promise.all([retainCustody(web), retainCustody(runtime)]);
      }
    } finally { receipt(Boolean(failure)); }
    if (failure) throw failure;
  })();
  process.once("SIGINT", () => shutdown().then(() => process.exit(0), () => process.exit(1)));
  process.once("SIGTERM", () => shutdown().then(() => process.exit(0), () => process.exit(1)));
  process.stdin.once("data", () => { void shutdown().catch(() => {}); });
  process.stdin.once("end", () => { void shutdown().catch(() => {}); });
  try {
    const deadline = performance.now() + 60000;
    runtime = spawn(base, ["-c", launch], { cwd: root, env: process.env, windowsHide: true, stdio: ["pipe", "ignore", "pipe"] });
    runtime.stderr.on("data", bytes => {
      const safe = bytes.toString("utf8").split(/\r?\n/).filter(line => /^Account browser fixture failed \([A-Za-z]+; [A-Za-z0-9_.,:\-<> ]+\)\.$/.test(line));
      if (safe.length) writeFileSync(resolve(evidenceDirectory(), "runtime-failure.txt"), safe.join("\n"));
    });
    while (!existsSync(stateFile)) {
      if (stopping) { await stopping; return; }
      if (!running(runtime)) throw new Error("Owned runtime exited before readiness");
      if (performance.now() >= deadline) throw new Error("Fixture startup exceeded 60 seconds");
      await pause(50);
    }
    const context = state();
    const env = { ...cleanEnvironment(), NODE_EXTRA_CA_CERTS: context.caFile, NEXT_TELEMETRY_DISABLED: "1", WSO_TVT_ACCOUNT_BROWSER_STATE_FILE: stateFile, WSO_PUBLIC_ORIGIN: context.baseURL, API_INTERNAL_ORIGIN: context.apiOrigin, WSO_OIDC_ISSUER: "https://w02.test", WSO_OIDC_CLIENT_ID: "fixture-web", WSO_OIDC_CLIENT_SECRET: randomBytes(32).toString("base64url"), WSO_AUTH_EXCHANGE_KEY: randomBytes(48).toString("base64url"), WSO_FLOW_ENCRYPTION_KEY: randomBytes(32).toString("base64url") };
    Object.assign(env, directoryAuthEnvironment(context));
    web = spawn(process.execPath, [fileURLToPath(import.meta.url), "--next"], { cwd: root, env, windowsHide: true, stdio: ["pipe", "ignore", "ignore"] });
    const ca = readFileSync(context.caFile);
    while (!(await health(context.baseURL + "/", ca))) {
      if (stopping) { await stopping; return; }
      if (!running(runtime) || !running(web)) throw new Error("Owned service exited before readiness");
      if (performance.now() >= deadline) throw new Error("Fixture startup exceeded 60 seconds");
      await pause(100);
    }
    writeFileSync(resolve(dirname(stateFile), "ready.json"), JSON.stringify({ ready: true, runtimePid: runtime.pid, nextPid: web.pid }), { mode: 0o600 });
    while (!stopping) {
      if (existsSync(resolve(dirname(stateFile), "shutdown.json"))) {
        await shutdown();
        break;
      }
      if (!running(runtime) || !running(web)) throw new Error("Owned service exited");
      await pause(100);
    }
    await stopping;
  } finally { await shutdown(); }
}
async function runPlaywright(args, env) {
  const child = spawn(process.execPath, args, { cwd: root, env, windowsHide: true, stdio: "inherit" });
  return await new Promise((done) => {
    child.once("error", () => done(1));
    child.once("exit", (code) => done(code ?? 1));
  });
}
export async function runBrowserSequence(run = runPlaywright) {
  for (const viewport of ["account-desktop", "account-mobile"]) {
    const id = randomUUID();
    const env = { ...process.env, WSO_TVT_ACCOUNT_BROWSER_VIEWPORT: viewport, WSO_TVT_ACCOUNT_BROWSER_RUN_ID: id,
      WSO_TVT_ACCOUNT_BROWSER_STATE_FILE: resolve(root, "auth-state", `tvt-account-${id}`, "context.json"),
      WSO_TVT_ACCOUNT_BROWSER_OUTPUT: resolve(root, "auth-state", `tvt-account-captures-${id}`) };
    // Each real Playwright lifecycle owns its own API/worker/database/context.
    // Successful process exit includes global teardown; never proceed on failure.
    const code = await run([resolve(root, "node_modules/@playwright/test/cli.js"), "test", "--config", "playwright.tvt-account.config.ts", `--project=${viewport}`], env);
    if (code !== 0) return code;
  }
  return 0;
}
export default async function setup() {
  if (!stateFile) throw new Error("Private state path is required");
  if (existsSync(dirname(stateFile))) throw new Error("Private fixture directory must be new");
  mkdirSync(resolve(root, "auth-state"), { recursive: true });
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url)], { cwd: root, env: { ...process.env, WSO_TEST_ACCOUNT_BROWSER: "1" }, windowsHide: true, stdio: ["pipe", "ignore", "ignore"] });
  const teardown = async () => {
    if (!running(child)) {
      if (child.exitCode !== 0) throw new Error("Owned coordinator failed; inspect safe fixture receipts");
      return;
    }
    child.stdin.once?.("error", () => {}); // A concurrent owned exit must not kill this custodian.
    child.stdin.end("close\n");
    const deadline = performance.now() + CLEANUP.setupMs;
    while (running(child) && performance.now() < deadline) await pause(50);
    if (running(child) || existsSync(stateFile))
      throw new Error("Owned fixture cleanup did not complete");
    if (child.exitCode !== 0) throw new Error("Owned fixture reported failure after cleanup; inspect safe receipts");
  };
  try {
    const deadline = performance.now() + 60000;
    while (!existsSync(resolve(dirname(stateFile), "ready.json"))) {
      if (!running(child)) throw new Error("Owned coordinator exited before readiness");
      if (performance.now() >= deadline) throw new Error("Fixture startup exceeded 60 seconds");
      await pause(50);
    }
    return teardown;
  } catch (error) {
    await teardown();
    throw error;
  }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv[2] === "--browser") process.exitCode = await runBrowserSequence();
    else if (process.argv[2] === "--next") await nextProcess();
    else await coordinator();
  } catch {
    // Do not print exception bodies, private context or Next/request output.
    process.stderr.write("Account browser coordinator failed.\n");
    process.stdin.destroy();
    process.exitCode = 1;
  }
}
