import { afterEach, expect, it, vi } from "vitest";
import fixture from "./fixtures/inert-device-qr.json";
import { readFileSync } from "node:fs";

async function helper() { return import("../src/lib/tvt/device-qr-image"); }
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("strictly parses the device information QR and rejects sharing, malformed and byte overflow", async () => {
  const { parseDeviceQr } = await helper();
  expect(parseDeviceQr("<sn>inert123</sn><user>fixture-user</user>")).toEqual({ serial: "INERT123", username: "fixture-user", qr_payload: "<sn>inert123</sn><user>fixture-user</user>" });
  for (const value of ['{"v":"QR10"}', "<sn>A</sn><user>u</user>extra", "<sn>A-B</sn><user>u</user>", "<sn>A</sn><user>\0</user>", `<sn>${"a".repeat(64)}</sn><user>u</user>`, `<sn>A</sn><user>${"한".repeat(22)}</user>`]) expect(() => parseDeviceQr(value)).toThrow("QR 이미지를 읽을 수 없습니다.");
});
it("rejects unsupported type and oversize file before decoding", async () => {
  const { decodeDeviceQrImage } = await helper();
  const create = vi.fn(); vi.stubGlobal("createImageBitmap", create);
  for (const file of [new File(["x"], "inert.svg", { type: "image/svg+xml" }), { size: 10 * 1024 * 1024 + 1, type: "image/png" } as File]) await expect(decodeDeviceQrImage(file)).rejects.toThrow("QR 이미지를 읽을 수 없습니다.");
  expect(create).not.toHaveBeenCalled();
});
it("closes decoded images before rejecting excessive dimensions or pixels", async () => {
  const { decodeDeviceQrImage } = await helper();
  for (const [width, height] of [[4097, 1], [2001, 2000]]) {
    const close = vi.fn(); vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width, height, close })));
    await expect(decodeDeviceQrImage(new File(["x"], "inert.png", { type: "image/png" }))).rejects.toThrow("QR 이미지를 읽을 수 없습니다.");
    expect(close).toHaveBeenCalledOnce();
  }
});

function pixels() {
  const scale = 5, width = fixture.rows.length * scale;
  const data = new Uint8ClampedArray(width * width * 4);
  for (let y = 0; y < width; y++) for (let x = 0; x < width; x++) {
    const shade = fixture.rows[Math.floor(y / scale)][Math.floor(x / scale)] === "1" ? 0 : 255;
    data.set([shade, shade, shade, 255], (y * width + x) * 4);
  }
  return { data, width, height: width };
}
it("decodes the actual inert QR matrix through real jsQR", async () => {
  const { decodeDeviceQrPixels } = await helper();
  const image = pixels();
  expect(decodeDeviceQrPixels(image.data, image.width, image.height)).toEqual({ serial: "INERT123", username: "fixture-user", qr_payload: "<sn>INERT123</sn><user>fixture-user</user>" });
  expect(() => decodeDeviceQrPixels(new Uint8ClampedArray(16), 2, 2)).toThrow("QR 이미지를 읽을 수 없습니다.");
});
it("runs the file/canvas path with real jsQR and releases bitmap/canvas on success and failure", async () => {
  const { decodeDeviceQrImage } = await helper();
  const image = pixels(), close = vi.fn();
  const canvas = { width: 0, height: 0, getContext: () => ({ drawImage: vi.fn(), getImageData: () => image }) };
  vi.stubGlobal("document", { createElement: () => canvas });
  vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: image.width, height: image.height, close })));
  const raw = readFileSync(new URL("./fixtures/inert-device-qr.png", import.meta.url));
  expect(raw.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))).toBe(true);
  expect((await decodeDeviceQrImage(new File([raw], "inert.png", { type: "image/png" }))).serial).toBe("INERT123");
  expect(close).toHaveBeenCalledOnce(); expect(canvas.width + canvas.height).toBe(0);
  image.data.fill(255);
  await expect(decodeDeviceQrImage(new File([raw], "inert.png", { type: "image/png" }))).rejects.toThrow("QR 이미지를 읽을 수 없습니다.");
  expect(close).toHaveBeenCalledTimes(2); expect(canvas.width + canvas.height).toBe(0);
});
