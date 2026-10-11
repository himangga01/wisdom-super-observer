import "server-only";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { ServiceError } from "../session";

export function ownedSharedMode(): boolean {
  const mode = process.env.WSO_TEST_LOCAL_MEDIA_SHARED;
  if (mode === undefined) return false;
  if (mode !== "1") throw new ServiceError(503);
  const file = process.env.WSO_TEST_LOCAL_DEVICE_BROWSER_STATE_FILE;
  if (!file) throw new ServiceError(503);
  try {
    const path = resolve(file);
    const folder = dirname(path);
    const roots = [
      resolve(process.cwd(), "auth-state"),
      resolve(process.cwd(), "../../auth-state"),
    ];
    if (
      basename(path) !== "context.json" ||
      !/^local-devices-[0-9a-f]{32}$/.test(basename(folder)) ||
      !roots.includes(dirname(folder)) ||
      realpathSync(path) !== path ||
      lstatSync(path).isSymbolicLink() ||
      lstatSync(folder).isSymbolicLink() ||
      lstatSync(path).size > 65536
    ) throw new Error("Owned context refused");
    const context = JSON.parse(readFileSync(path, "utf8"));
    const shared = context.sharedMedia;
    const profile: Record<string, number> = {
      base_originals: 2,
      main_originals: 1,
      viewers: 12,
      physical_slots: 16,
      worker_process_bytes: 2147483648,
      native_process_bytes: 536870912,
      decoder_process_bytes: 536870912,
      retained_host_bytes: 1073741824,
    };
    if (
      context.schemaVersion !== 1 ||
      context.proofKind !== "owned-local-device-native-pipeline" ||
      context.role !== "OWNER" ||
      context.baseURL !== "https://localhost:3543" ||
      !shared ||
      Object.keys(shared).sort().join(",") !== "enabled,profile,schemaVersion" ||
      shared.schemaVersion !== 1 ||
      shared.enabled !== true ||
      !shared.profile ||
      Object.keys(shared.profile).sort().join(",") !== Object.keys(profile).sort().join(",") ||
      Object.entries(profile).some(([key, value]) => shared.profile[key] !== value)
    ) throw new Error("Owned shared profile refused");
    return true;
  } catch {
    throw new ServiceError(503);
  }
}
