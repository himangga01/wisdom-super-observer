// New local OWNER runtime. Reuses reviewed custody and signed-auth validators.
import { spawn, spawnSync } from "node:child_process";
import { readFileSync, existsSync, statSync, writeFileSync, mkdirSync } from "node:fs";
import { createServer, request } from "node:https";
import { dirname, resolve, basename } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const root = fileURLToPath(new URL("../../", import.meta.url));
export async function admittedHelpers({ read = readFileSync, importer = url => import(url) } = {}) {
  const file = resolve(root, "scripts/test-tvt-account/server.mjs");
  if (createHash("sha256").update(read(file)).digest("hex") !== "65fa1c90b66440284e632e25b38ddd6d93379416826b55caaba43c112a681173") throw new Error("Borrowed browser helper source refused");
  return await importer(pathToFileURL(file).href);
}
const { stopOwned, retainCustody, CLEANUP, directoryAuthEnvironment } = await admittedHelpers();
const pause = ms => new Promise(done => setTimeout(done, ms));
const running = child => Boolean(child && child.exitCode === null && child.signalCode == null);
const cleanEnvironment = () => Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(WSO_|PG|DATABASE|NODE_)/.test(key) && !["SSL_CERT_FILE", "SSL_CERT_DIR"].includes(key)));

export function validateStateFile(value) {
  if (typeof value !== "string" || resolve(value) !== value.replaceAll("/", process.platform === "win32" ? "\\" : "/") || basename(value) !== "context.json" || dirname(dirname(value)) !== resolve(root, "auth-state") || !/^local-devices-[0-9a-f]{32}$/.test(basename(dirname(value)))) throw new Error("Explicit owned local state required");
  return value;
}
export function localAuthEnvironment(context) {
  if (context.proofKind !== "owned-local-device-native-pipeline" || context.schemaVersion !== 1 || context.role !== "OWNER" || context.baseURL !== "https://localhost:3543") throw new Error("Owned local state refused");
  return directoryAuthEnvironment({ directoryMode: true, nextAuth: context.nextAuth }, { WSO_TEST_DIRECTORY_BROWSER: "1" });
}
function state(file) {
  if (!existsSync(file) || statSync(file).size > 65536) throw new Error("Private local state unavailable");
  const context = JSON.parse(readFileSync(file, "utf8"));
  localAuthEnvironment(context);
  return context;
}
export function installDurableStop(control, callback, { exists = existsSync } = {}) {
  // External stdin EOF is not a stop request. Only this durable owned file is.
  return async () => { if (exists(control)) await callback(); };
}
export async function deliverRuntimeStop(runtime, folder, { deadline, exists = existsSync, write = writeFileSync, pause: wait = pause, now = () => performance.now(), onOverrun = () => {} } = {}) {
  let reported = false;
  while (running(runtime)) {
    if (exists(folder)) {
      try { write(resolve(folder, "runtime-shutdown.json"), "{}", { mode: 0o600 }); return true; }
      catch (error) { if (error.code !== "ENOENT") throw error; }
    }
    if (!reported && now() >= deadline) { reported = true; onOverrun(); }
    await wait(50);
  }
  return false;
}
async function health(url, ca) {
  return await new Promise(done => {
    const call = request(url, { ca, rejectUnauthorized: true, timeout: 1000 }, response => { response.resume(); done(response.statusCode === 200); });
    call.on("timeout", () => call.destroy()); call.on("error", () => done(false)); call.end();
  });
}
export async function closeNextOwned(app, server) {
  server.close(); server.closeAllConnections();
  await app.close();
  // This subordinate owns no DB/native custody; settle after actual Next close,
  // even if development watchers retain otherwise idle event-loop handles.
  process.exit(0);
}
async function nextProcess(file) {
  const context = state(file);
  const { default: next } = await import(pathToFileURL(resolve(root, "apps/web/node_modules/next/dist/server/next.js")).href);
  const app = next({ dev: true, dir: resolve(root, "apps/web"), hostname: "localhost", port: 3543 });
  await app.prepare();
  const handler = app.getRequestHandler();
  const server = createServer({ key: readFileSync(context.keyFile), cert: readFileSync(context.certificateFile) }, (req, res) => handler(req, res));
  server.on("error", () => { process.exitCode = 1; void app.close(); });
  await new Promise((done, reject) => { server.once("error", reject); server.listen(3543, "localhost", done); });
  writeFileSync(resolve(dirname(file), "next-bound.json"), JSON.stringify({ pid: process.pid, port: 3543 }), { mode: 0o600 });
  let stopping = false;
  const close = async () => { if (stopping) return; stopping = true; await closeNextOwned(app, server); };
  process.stdin.once("data", () => { void close(); });
  process.stdin.once("end", () => { void close(); });
}
export async function coordinator() {
  if (process.env.WSO_TEST_LOCAL_DEVICE_BROWSER !== "1" || process.env.WSO_TEST_LOCAL_DEVICE_NATIVE !== "real") throw new Error("Explicit local fixture activation required");
  const file = validateStateFile(process.env.WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE);
  if (existsSync(dirname(file))) throw new Error("Owned local private directory must be new");
  const evidence = resolve(root, ".superpowers/verification/local-device-browser-runtime", basename(dirname(file)));
  const python = resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  const info = spawnSync(python, ["-c", "import json,sys,sysconfig;print(json.dumps([sys._base_executable,sysconfig.get_paths()['purelib'],sys.prefix]))"], { encoding: "utf8", windowsHide: true, timeout: 5000 });
  if (info.status !== 0) throw new Error("Trusted Python unavailable");
  const [base, site, prefix] = JSON.parse(info.stdout);
  const launch = `import site,runpy,sys;sys.prefix=${JSON.stringify(prefix)};site.addsitedir(${JSON.stringify(site)});sys.path.insert(0,${JSON.stringify(root)});runpy.run_path(${JSON.stringify(resolve(root, "scripts/test-local-devices/runtime.py"))},run_name='__main__')`;
  let runtime, web, stopping;
  const events = [];
  const receipt = failure => {
    mkdirSync(evidence, { recursive: true });
    const entry = { runtimePid: runtime?.pid ?? null, runtimeExit: runtime?.exitCode ?? null, nextPid: web?.pid ?? null, nextExit: web?.exitCode ?? null, stateRemoved: !existsSync(file), custodyRetained: [web, runtime].some(running), failureReported: failure };
    events.push(entry); writeFileSync(resolve(evidence, "coordinator-resources.json"), JSON.stringify({ ...entry, events }, null, 2));
  };
  const shutdown = () => stopping ??= (async () => {
    const end = performance.now() + CLEANUP.coordinatorMs;
    let failure;
    try {
      try { await stopOwned(web, { deadline: Math.min(end, performance.now() + CLEANUP.nextMs) }); } catch (error) { failure = error; receipt(true); }
      await deliverRuntimeStop(runtime, dirname(file), { deadline: end, onOverrun: () => { failure ??= new Error("Runtime stop delivery deadline exceeded; custody retained"); receipt(true); } });
      try { await stopOwned(runtime, { deadline: Math.min(end, performance.now() + CLEANUP.runtimeMs), resourceOwner: true }); } catch (error) { failure ??= error; receipt(true); }
      if ([web, runtime].some(running)) { receipt(true); await Promise.all([retainCustody(web), retainCustody(runtime)]); }
    } finally { receipt(Boolean(failure)); }
    if (failure) throw failure;
  })();
  process.once("SIGINT", () => { void shutdown().catch(() => { process.exitCode = 1; }); });
  process.once("SIGTERM", () => { void shutdown().catch(() => { process.exitCode = 1; }); });
  const checkStop = installDurableStop(resolve(dirname(file), "shutdown.json"), shutdown);
  try {
    runtime = spawn(base, ["-c", launch], { cwd: root, env: process.env, windowsHide: true, stdio: ["pipe", "ignore", "ignore"] });
    const deadline = performance.now() + 90000;
    while (!existsSync(file)) { if (!running(runtime) || performance.now() >= deadline) throw new Error("Owned local runtime readiness failed"); await checkStop(); if (stopping) return await stopping; await pause(100); }
    const context = state(file);
    const env = { ...cleanEnvironment(), ...localAuthEnvironment(context), NODE_EXTRA_CA_CERTS: context.caFile, NEXT_TELEMETRY_DISABLED: "1", WSO_PUBLIC_ORIGIN: context.baseURL, API_INTERNAL_ORIGIN: context.apiOrigin, WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE: file };
    web = spawn(process.execPath, [fileURLToPath(import.meta.url), "--next"], { cwd: root, env, windowsHide: true, stdio: ["pipe", "ignore", "ignore"] });
    const bound = resolve(dirname(file), "next-bound.json");
    while (!existsSync(bound)) { if (!running(web) || !running(runtime) || performance.now() >= deadline) throw new Error("Owned Next bind failed"); await checkStop(); if (stopping) return await stopping; await pause(100); }
    if (JSON.parse(readFileSync(bound)).pid !== web.pid) throw new Error("Next ownership refused");
    while (!(await health(context.baseURL + "/", readFileSync(context.caFile)))) { if (!running(web) || !running(runtime) || performance.now() >= deadline) throw new Error("Owned local HTTPS readiness failed"); await checkStop(); if (stopping) return await stopping; await pause(100); }
    writeFileSync(resolve(dirname(file), "ready.json"), JSON.stringify({ ready: true, publicURL: context.baseURL + "/api/auth/login", runtimePid: runtime.pid, nextPid: web.pid, nativeVerificationExecuted: false }), { mode: 0o600 });
    while (!stopping) { if (!running(web) || !running(runtime)) throw new Error("Owned local service exited"); await checkStop(); await pause(100); }
    await stopping;
  } finally { await shutdown(); }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { if (process.argv[2] === "--next") await nextProcess(validateStateFile(process.env.WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE)); else await coordinator(); }
  catch { process.stderr.write("Local device browser coordinator failed.\n"); process.exitCode = 1; }
}
