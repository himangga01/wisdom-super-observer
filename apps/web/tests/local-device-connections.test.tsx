// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConnectionForm } from "../src/features/connections/connection-form";
import { parseConnectionBody, publicConnection, type ConnectionView } from "../src/lib/connections";
import * as qrImage from "../src/lib/tvt/device-qr-image";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const device = { serial: "INERT123", country: "KR" };
const body = { kind: "TVT_DEVICE", alias: "입구", site: "본점", username: "fixture-user", password: "fixture-password", device };
const store = { id: "10000000-0000-4000-8000-000000000001", tenant_id: "20000000-0000-4000-8000-000000000001", active: true, name: "본점", timezone: "Asia/Seoul" };
function mount(onSubmit = vi.fn(async () => {}), onCancel = vi.fn(), connection?: ConnectionView) {
  return { onSubmit, onCancel, ...render(<ConnectionForm connection={connection} stores={[store]} busy={false} onSubmit={onSubmit} onCancel={onCancel} />) };
}
function type(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
function enter() { type("연결 유형", "TVT_DEVICE"); type("연결 이름", "입구"); type("사이트 / 주소", "본점"); type("장치번호", "inert123"); type("아이디", "fixture-user"); type("비밀번호", "fixture-password"); }

it("retains private device inputs in writes and rejects type mismatch and credential byte limits", () => {
  expect(parseConnectionBody("create", body)).toMatchObject({ device });
  for (const invalid of [{ ...body, device: undefined }, { ...body, kind: "TVT_ACCOUNT" }, { ...body, password: "한".repeat(22) }, { ...body, device: { ...device, sourceType: "TVT_ACCOUNT" } }]) {
    expect(() => parseConnectionBody("create", invalid)).toThrow("Invalid connection input");
  }
  expect(() => parseConnectionBody("patch", { expected_generation: 1, device })).toThrow();
});
it("clears all private DOM fields before submitting a canonical device body without changing location", async () => {
  const { onSubmit } = mount(); enter();
  await act(async () => fireEvent.submit(screen.getByRole("button", { name: "연결 저장" }).closest("form")!));
  expect(onSubmit).toHaveBeenCalledWith({ ...body, store_ids: [] });
  for (const label of ["장치번호", "아이디", "비밀번호"]) expect(screen.getByLabelText(label)).toHaveValue("");
  expect(screen.getByLabelText("사이트 / 주소")).toHaveValue("본점");
  expect(localStorage.length + sessionStorage.length).toBe(0);
});
it("clears private fields on store selection, type change and cancellation", () => {
  const { onCancel } = mount(); enter();
  fireEvent.click(screen.getByLabelText("본점"));
  expect(screen.getByLabelText("장치번호")).toHaveValue("");
  type("장치번호", "inert123"); type("아이디", "fixture-user"); type("비밀번호", "fixture-password");
  type("연결 유형", "TVT_ACCOUNT");
  expect(screen.getByLabelText("아이디")).toHaveValue("");
  type("아이디", "fixture-user"); fireEvent.click(screen.getByRole("button", { name: "취소" }));
  expect(screen.getByLabelText("아이디")).toHaveValue(""); expect(onCancel).toHaveBeenCalledOnce();
});
it("preserves legacy metadata editing while complete device replacement has fresh inputs", () => {
  const connection = publicConnection({ id: store.id, tenant_id: store.id, kind: "TVT_DEVICE", alias: "입구", site: "본점", generation: 1, status: "NOT_VERIFIED", last_success: null, store_ids: [], device });
  mount(undefined, undefined, connection);
  expect(screen.queryByLabelText("장치번호")).toBeNull();
  fireEvent.click(screen.getByLabelText("계정 정보 교체"));
  expect(screen.getByLabelText("장치번호")).toHaveValue("");
  type("장치번호", "inert123"); fireEvent.click(screen.getByLabelText("계정 정보 교체"));
  fireEvent.click(screen.getByLabelText("계정 정보 교체"));
  expect(screen.getByLabelText("장치번호")).toHaveValue("");
});

it("fills private QR fields locally, retains the human location, and clears payload after submit", async () => {
  vi.spyOn(qrImage, "decodeDeviceQrImage").mockResolvedValue({ ...device, username: "fixture-user", qr_payload: "<sn>INERT123</sn><user>fixture-user</user>" });
  const { onSubmit } = mount(); enter();
  await act(async () => fireEvent.change(screen.getByLabelText("QR 이미지 선택"), { target: { files: [new File(["inert"], "inert.png", { type: "image/png" })] } }));
  expect(screen.getByLabelText("장치번호")).toHaveValue("INERT123");
  expect(screen.getByLabelText("아이디")).toHaveValue("fixture-user");
  expect(screen.getByLabelText("비밀번호")).toHaveValue("");
  expect(screen.getByLabelText("사이트 / 주소")).toHaveValue("본점");
  type("비밀번호", "fixture-password");
  await act(async () => fireEvent.submit(screen.getByRole("button", { name: "연결 저장" }).closest("form")!));
  expect(onSubmit).toHaveBeenCalledWith({ ...body, store_ids: [], device: { ...device, qr_payload: "<sn>INERT123</sn><user>fixture-user</user>" } });
  for (const label of ["장치번호", "아이디", "비밀번호", "QR 이미지 선택"]) expect(screen.getByLabelText(label)).toHaveValue("");
});

it.each(["cancel", "type", "store", "unmount", "selection"])("ignores late QR completion after %s", async (action) => {
  let resolve!: (input: qrImage.DeviceQrInput) => void;
  const decode = vi.spyOn(qrImage, "decodeDeviceQrImage").mockImplementationOnce(() => new Promise(done => { resolve = done; })).mockResolvedValue({ serial: "NEW123", username: "next-user", qr_payload: "<sn>NEW123</sn><user>next-user</user>" });
  const { unmount } = mount(); enter();
  fireEvent.change(screen.getByLabelText("QR 이미지 선택"), { target: { files: [new File(["inert"], "inert.png", { type: "image/png" })] } });
  if (action === "cancel") fireEvent.click(screen.getByRole("button", { name: "취소" }));
  if (action === "type") type("연결 유형", "TVT_ACCOUNT");
  if (action === "store") fireEvent.click(screen.getByLabelText("본점"));
  if (action === "unmount") unmount();
  if (action === "selection") await act(async () => fireEvent.change(screen.getByLabelText("QR 이미지 선택"), { target: { files: [new File(["new"], "new.png", { type: "image/png" })] } }));
  await act(async () => resolve({ serial: "STALE123", username: "stale-user", qr_payload: "<sn>STALE123</sn><user>stale-user</user>" }));
  expect(decode).toHaveBeenCalled();
  expect(screen.queryByDisplayValue("STALE123")).toBeNull();
  expect(screen.queryByDisplayValue("stale-user")).toBeNull();
  if (action === "selection") expect(screen.getByLabelText("장치번호")).toHaveValue("NEW123");
});

it("clears an in-flight QR and releases the reading state when available store scope changes", async () => {
  let resolve!: (input: qrImage.DeviceQrInput) => void;
  vi.spyOn(qrImage, "decodeDeviceQrImage").mockImplementation(() => new Promise(done => { resolve = done; }));
  const { rerender, onSubmit, onCancel } = mount(); enter();
  fireEvent.change(screen.getByLabelText("QR 이미지 선택"), { target: { files: [new File(["inert"], "inert.png", { type: "image/png" })] } });
  rerender(<ConnectionForm stores={[]} busy={false} onSubmit={onSubmit} onCancel={onCancel} />);
  await act(async () => resolve({ serial: "STALE123", username: "stale-user", qr_payload: "<sn>STALE123</sn><user>stale-user</user>" }));
  expect(screen.queryByDisplayValue("STALE123")).toBeNull();
  expect(screen.getByRole("button", { name: "연결 저장" })).toBeEnabled();
  expect(screen.getByLabelText("국가")).toHaveValue("KR");
});
