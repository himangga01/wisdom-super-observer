import jsQR from "jsqr";

const error = () => new Error("QR 이미지를 읽을 수 없습니다.");
export type DeviceQrInput = { serial: string; username: string; qr_payload: string };
export function parseDeviceQr(payload: string): DeviceQrInput {
  if (typeof payload !== "string" || new TextEncoder().encode(payload).length > 4096 || payload.includes("\0")) throw error();
  const match = /^<sn>([A-Za-z0-9]{1,63})<\/sn><user>([^<>]+)<\/user>$/.exec(payload);
  if (!match || new TextEncoder().encode(match[2]).length > 63) throw error();
  return { serial: match[1].toUpperCase(), username: match[2], qr_payload: payload };
}

export function decodeDeviceQrPixels(data: Uint8ClampedArray, width: number, height: number): DeviceQrInput {
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width > 4096 || height > 4096 || width * height > 4_000_000 || data.length !== width * height * 4) throw error();
  const result = jsQR(data, width, height, { inversionAttempts: "attemptBoth" });
  if (!result) throw error();
  return parseDeviceQr(result.data);
}

export async function decodeDeviceQrImage(file: File): Promise<DeviceQrInput> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type) || file.size < 1 || file.size > 10 * 1024 * 1024) throw error();
  let bitmap: ImageBitmap | undefined;
  let canvas: HTMLCanvasElement | undefined;
  try {
    bitmap = await createImageBitmap(file);
    const { width, height } = bitmap;
    if (width < 1 || height < 1 || width > 4096 || height > 4096 || width * height > 4_000_000) throw error();
    canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw error();
    context.drawImage(bitmap, 0, 0);
    const pixels = context.getImageData(0, 0, width, height);
    return decodeDeviceQrPixels(pixels.data, width, height);
  } catch {
    throw error();
  } finally {
    bitmap?.close();
    if (canvas) { canvas.width = 0; canvas.height = 0; }
  }
}
