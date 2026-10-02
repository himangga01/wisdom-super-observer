// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as client from "../src/lib/tvt/flow-api-client";
import * as accountClient from "../src/lib/tvt/account-api-client";
import { SessionBoundary } from "../src/features/tvt/account/SessionBoundary";
import type { Bootstrap } from "../src/lib/tvt/api-client";

const tenant = "10000000-0000-4000-8000-000000000001";
const flow = "20000000-0000-4000-8000-000000000001";
const challenge = "30000000-0000-4000-8000-000000000001";
const selection = { brand: "SuperLivePlus", region: "KR" } as const;
const bootstrap: Bootstrap = { selected_tenant_id: tenant, profile_id: "ui-test", ...selection, locale: "en", timezone: "Asia/Seoul", supported_locales: ["en"], consent: { version: "v1", status: "accepted", decided_at: "2026-10-02T00:00:00Z", terms: { source_reference: "agreement/ServiceTerms_en.html", url: "https://policy.test/terms" }, privacy: { source_reference: "agreement/PrivacyStatement_en.html", url: "https://policy.test/privacy" } }, identity: { state: "unlinked", accounts: [] }, menu: [{ id: "local-account", label: "Account", path: "/tvt/account" }] };
const image = { challenge_id: challenge, generation: 1, media_type: "image/png" as const, image_base64: "iVBORw0KGgpJRU5ErkJggg==" };
function view(purpose: "register" | "recover", state: client.AccountFlowView["state"], extra: Partial<client.AccountFlowView> = {}): client.AccountFlowView {
  return { ...selection, purpose, flow_id: flow, request_id: "ui:request.1", state, return_to_login: state === "COMPLETE", automatic_retry_permitted: false, ...extra };
}
let api: client.AccountFlowApi;
let revoke: ReturnType<typeof vi.fn>;
beforeEach(() => {
  const operation = (state: client.AccountFlowView["state"], extra: Partial<client.AccountFlowView> = {}) => vi.fn(async (_tenant: string, body: client.AccountFlowReference | client.AccountFlowStart) => view(body.purpose, state, extra));
  api = { start: operation("CREATED", { expires_in_seconds: 300 }), state: operation("CODE_SENT"), existence: vi.fn(async (_tenant, body) => view(body.purpose, "EXISTENCE", { exists: body.purpose === "recover" })), image: operation("IMAGE_AVAILABLE", { image }), issueCode: operation("CODE_SENT", { resend_wait_seconds: 120 }), register: operation("COMPLETE"), recover: operation("COMPLETE"), cancel: operation("CLOSED") };
  vi.spyOn(client, "accountFlowClient").mockReturnValue(api);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:owned-test") });
  revoke = vi.fn(); Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revoke });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });
function mount(userId = "ui-actor", current = bootstrap) { return render(<SessionBoundary userId={userId} bootstrap={current} csrf="ui-csrf" requery={async () => current} />); }
function open(purpose: "register" | "recover") { fireEvent.click(screen.getByRole("button", { name: purpose === "register" ? "계정 등록" : "비밀번호 찾기" })); }
function enter(purpose: "register" | "recover", mode: "email" | "phone" = "email") {
  if (mode === "phone") {
    fireEvent.change(screen.getByLabelText("계정 방식"), { target: { value: "phone" } });
    const options = (screen.getByLabelText("국가 전화 코드") as HTMLSelectElement).options;
    expect(options).toHaveLength(197);
    fireEvent.change(screen.getByLabelText("국가 전화 코드"), { target: { value: Array.from(options).find(o => o.value.startsWith("KR:"))!.value } });
  }
  fireEvent.change(screen.getByLabelText(mode === "email" ? "이메일" : "전화번호"), { target: { value: mode === "email" ? "synthetic@example.test" : "00101234" } });
  if (purpose === "register") fireEvent.click(screen.getByLabelText(/서비스 약관과 개인정보/));
}
async function sendCode() { fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); await screen.findByText(/확인 코드를 보냈습니다/); }
function finalInputs() {
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "DemoPass9!" } });
  fireEvent.change(screen.getByLabelText("확인 코드"), { target: { value: "246810" } });
}
it.each(["register", "recover"] as const)("exposes %s entry and cancels back to login", purpose => {
  mount(); open(purpose); expect(screen.getByLabelText("계정 방식")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "로그인으로 돌아가기" }));
  expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeVisible();
});
it.each([["register", "email"], ["register", "phone"], ["recover", "email"], ["recover", "phone"]] as const)("submits %s %s through start, existence, code and purpose-specific final without auto-login", async (purpose, mode) => {
  mount(); open(purpose); enter(purpose, mode); await sendCode(); finalInputs();
  expect(api.start).toHaveBeenCalledWith(tenant, { ...selection, purpose, mode, account: mode === "email" ? "synthetic@example.test" : "00101234", ...(mode === "phone" ? { country_code: "82" } : {}) }, expect.any(AbortSignal));
  expect(api.existence).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: purpose === "register" ? "등록 완료" : "비밀번호 변경" }));
  await screen.findByRole("button", { name: "TVT 로그인" });
  expect(api[purpose]).toHaveBeenCalledWith(tenant, { ...selection, purpose, flow_id: flow, dynamic_code: "246810", ...(purpose === "register" ? { password: "DemoPass9!" } : { new_password: "DemoPass9!" }) }, expect.any(AbortSignal));
  expect(localStorage.length + sessionStorage.length).toBe(0);
});
it.each(["register", "recover"] as const)("preserves false existence and checks source-appropriate %s account availability", async purpose => {
  api.existence = vi.fn(async () => view(purpose, "EXISTENCE", { exists: false }));
  mount(); open(purpose); enter(purpose); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  if (purpose === "recover") { await screen.findByRole("alert"); expect(api.issueCode).not.toHaveBeenCalled(); }
  else { await screen.findByText(/확인 코드를 보냈습니다/); expect(api.issueCode).toHaveBeenCalledOnce(); }
});
it.each([["register", "IMAGE_REQUIRED", 6], ["register", "IMAGE_REJECTED", 6], ["recover", "IMAGE_REQUIRED", 4]] as const)("retains %s %s image readiness at %i characters without treating it as completion", async (purpose, state, length) => {
  vi.mocked(api.issueCode).mockResolvedValueOnce(view(purpose, state, { image }));
  mount(); open(purpose); enter(purpose); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findByAltText("계정 확인 이미지");
  expect(screen.queryByRole("button", { name: "TVT 로그인" })).toBeNull();
  const button = screen.getByRole("button", { name: "이미지 확인 후 코드 요청" });
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "x".repeat(length - 1) } }); expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "x".repeat(length) } }); expect(button).toBeEnabled();
  fireEvent.click(button); await screen.findByText(/확인 코드를 보냈습니다/);
  expect(api.issueCode).toHaveBeenLastCalledWith(tenant, { ...selection, purpose, flow_id: flow, challenge_id: challenge, challenge_generation: 1, image_code: "x".repeat(length) }, expect.any(AbortSignal));
  expect(revoke).toHaveBeenCalledWith("blob:owned-test");
});
it("requires registration agreement and two password categories at 8–16 characters", async () => {
  mount(); open("register"); fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "synthetic@example.test" } });
  fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); expect(api.start).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText(/서비스 약관과 개인정보/)); await sendCode();
  for (const password of ["short1", "onlyletters", "12345678", "letter_s", "letter-s", "A".repeat(16) + "1"]) {
    fireEvent.change(screen.getByLabelText("확인 코드"), { target: { value: "246810" } });
    fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: password } });
    fireEvent.click(screen.getByRole("button", { name: "등록 완료" })); expect(api.register).not.toHaveBeenCalled();
  }
  finalInputs(); fireEvent.click(screen.getByRole("button", { name: "등록 완료" })); await screen.findByRole("button", { name: "TVT 로그인" });
  expect(api.register).toHaveBeenCalledOnce();
});
it.each((["register", "recover"] as const).flatMap(purpose => (["unavailable", "protocol"] as const).flatMap(failure => (["code", "image"] as const).map(attempt => ({ purpose, failure, attempt })))) )("blocks all downstream $purpose operations after $failure existence failure on a later $attempt attempt", async ({ purpose, failure, attempt }) => {
  vi.mocked(api.existence).mockRejectedValueOnce(failure === "unavailable" ? new client.AccountFlowError(503, "ACCOUNT_UNAVAILABLE", "private existence text") : new Error("private malformed existence response"));
  vi.mocked(api.issueCode).mockImplementation(async (_tenant, body) => view(body.purpose, "CODE_SENT", { resend_wait_seconds: 0 }));
  mount(); open(purpose); enter(purpose); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findAllByRole("alert"); await act(async () => {});
  if (attempt === "code") fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  const uncheckedImage = screen.queryByRole("button", { name: "이미지 새로 요청" });
  if (attempt === "image" && uncheckedImage) fireEvent.click(uncheckedImage);
  finalInputs();
  fireEvent.submit(screen.getByLabelText("새 비밀번호").closest("form")!);
  await act(async () => {});
  expect(api.issueCode).not.toHaveBeenCalled(); expect(api.image).not.toHaveBeenCalled();
  expect(api.register).not.toHaveBeenCalled(); expect(api.recover).not.toHaveBeenCalled();
  expect(api.start).toHaveBeenCalledOnce(); expect(api.existence).toHaveBeenCalledOnce();
  expect(screen.queryByText("private existence text")).toBeNull(); expect(screen.queryByText("private malformed existence response")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "새로 시작" }));
  enter(purpose); await sendCode();
  expect(api.start).toHaveBeenCalledTimes(2); expect(api.existence).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.issueCode).mock.invocationCallOrder[0]).toBeGreaterThan(vi.mocked(api.existence).mock.invocationCallOrder[1]);
  fireEvent.click(screen.getByRole("button", { name: "이미지 새로 요청" })); await screen.findByAltText("계정 확인 이미지");
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: purpose === "register" ? "123456" : "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "이미지 확인 후 코드 요청" })); await screen.findByText(/확인 코드를 보냈습니다/);
  finalInputs(); fireEvent.click(screen.getByRole("button", { name: purpose === "register" ? "등록 완료" : "비밀번호 변경" }));
  await screen.findByRole("button", { name: "TVT 로그인" });
  expect(api.image).toHaveBeenCalledOnce(); expect(api.issueCode).toHaveBeenCalledTimes(2); expect(api[purpose]).toHaveBeenCalledOnce();
});
it("counts one-second resend ticks and expires local flow without automatic resend", async () => {
  mount(); open("register"); enter("register"); vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); await act(async () => {});
  expect(screen.getByText(/120초 후/)).toBeVisible();
  await act(async () => { vi.advanceTimersByTime(1000); }); expect(screen.getByText(/119초 후/)).toBeVisible();
  await act(async () => { vi.advanceTimersByTime(119000); }); expect(screen.getByRole("button", { name: "확인 코드 다시 요청" })).toBeEnabled(); expect(api.issueCode).toHaveBeenCalledOnce();
  finalInputs(); await act(async () => { vi.advanceTimersByTime(180000); });
  expect(screen.getByRole("alert")).toHaveTextContent("만료"); expect(screen.getByLabelText("새 비밀번호")).toHaveValue(""); expect(screen.getByLabelText("확인 코드")).toHaveValue("");
  expect(api.register).not.toHaveBeenCalled();
});
it("blocks unknown final outcome and only reconciles with an explicit state read", async () => {
  vi.mocked(api.register).mockResolvedValueOnce(view("register", "UNKNOWN_OUTCOME", { error_code: "ACCOUNT_TRANSPORT_FAILED" }));
  vi.mocked(api.state).mockResolvedValueOnce(view("register", "UNKNOWN_OUTCOME"));
  mount(); open("register"); enter("register"); await sendCode(); finalInputs(); fireEvent.click(screen.getByRole("button", { name: "등록 완료" }));
  await screen.findByText(/처리 결과를 확인할 수 없습니다/);
  expect(screen.getByRole("button", { name: "등록 완료" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "현재 상태 확인" })); await waitFor(() => expect(api.state).toHaveBeenCalledOnce());
  expect(api.register).toHaveBeenCalledOnce(); expect(screen.queryByRole("button", { name: "새로 시작" })).toBeNull();
  expect(screen.getByLabelText("새 비밀번호")).toHaveValue("");
});
it.each(["FAILED", "CLOSED", "EXPIRED"] as const)("clears %s secrets and offers a user-triggered fresh start", async state => {
  vi.mocked(api.issueCode).mockResolvedValueOnce(view("register", state));
  mount(); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findByRole("button", { name: "새로 시작" }); expect(screen.getByLabelText("이메일")).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "새로 시작" })); expect(api.start).toHaveBeenCalledOnce();
});
it("cancels immediately, revokes owned image and ignores a late code result and finally", async () => {
  vi.mocked(api.issueCode).mockResolvedValueOnce(view("register", "IMAGE_REQUIRED", { image }));
  mount(); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); await screen.findByAltText("계정 확인 이미지");
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.issueCode).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  fireEvent.change(screen.getByLabelText("이미지 확인 코드"), { target: { value: "123456" } }); fireEvent.click(screen.getByRole("button", { name: "이미지 확인 후 코드 요청" }));
  fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "replacement@example.test" } });
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "Replacement9!" } });
  await act(async () => { resolve(view("register", "CODE_SENT")); });
  expect(screen.getByLabelText("새 비밀번호")).toHaveValue("Replacement9!");
  expect(screen.queryByText(/확인 코드를 보냈습니다/)).toBeNull(); expect(revoke).toHaveBeenCalled();
  expect(vi.mocked(api.issueCode).mock.calls[1][2].aborted).toBe(true);
});
it.each(["actor", "tenant", "region", "brand", "consent"] as const)("fences delayed results when %s scope is replaced", async changed => {
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.start).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const mounted = mount(); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  const current = { ...bootstrap, ...(changed === "tenant" ? { selected_tenant_id: "10000000-0000-4000-8000-000000000002" } : changed === "region" ? { region: "EU" } : changed === "brand" ? { brand: "OtherBrand" } : changed === "consent" ? { consent: { ...bootstrap.consent, status: "required" } } : {}) } as Bootstrap;
  mounted.rerender(<SessionBoundary userId={changed === "actor" ? "replacement-actor" : "ui-actor"} bootstrap={current} csrf="ui-csrf" requery={async () => current} />);
  await act(async () => { resolve(view("register", "CREATED")); });
  expect(api.existence).not.toHaveBeenCalled(); expect(vi.mocked(api.start).mock.calls[0][2].aborted).toBe(true);
});
it("disposes countdown and all inputs on navigation and pagehide", async () => {
  mount(); open("recover"); enter("recover"); vi.useFakeTimers(); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); await act(async () => {});
  finalInputs(); fireEvent.click(screen.getByRole("button", { name: "로그인으로 돌아가기" }));
  expect(vi.getTimerCount()).toBe(0); expect(screen.getByLabelText("비밀번호")).toHaveValue("");
  open("register"); enter("register"); fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "DemoPass9!" } });
  fireEvent(window, new Event("pagehide")); expect(screen.queryByLabelText("새 비밀번호")).toBeNull(); expect(vi.getTimerCount()).toBe(0);
});
it("cannot bypass a negative recovery existence check with a second code click", async () => {
  api.existence = vi.fn(async () => view("recover", "EXISTENCE", { exists: false }));
  mount(); open("recover"); enter("recover"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findByRole("alert"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await act(async () => {}); expect(api.issueCode).not.toHaveBeenCalled();
});
it("keeps an uncertain final write blocked after a nonterminal state read", async () => {
  vi.mocked(api.register).mockResolvedValueOnce(view("register", "UNKNOWN_OUTCOME"));
  mount(); open("register"); enter("register"); await sendCode(); finalInputs();
  fireEvent.click(screen.getByRole("button", { name: "등록 완료" })); await screen.findByText(/처리 결과를 확인할 수 없습니다/);
  fireEvent.click(screen.getByRole("button", { name: "현재 상태 확인" })); await waitFor(() => expect(api.state).toHaveBeenCalledOnce());
  await act(async () => {});
  expect(screen.getByRole("button", { name: "등록 완료" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "현재 상태 확인" })).toBeEnabled();
  expect(api.register).toHaveBeenCalledOnce();
});
it.each((["register", "recover"] as const).flatMap(purpose => (["unavailable", "protocol"] as const).map(failure => ({ purpose, failure }))))("retains expired pending $purpose uncertainty after a failed $failure reconciliation and permits a later explicit read", async ({ purpose, failure }) => {
  let finishFinal!: (value: client.AccountFlowView) => void;
  vi.mocked(api[purpose]).mockImplementationOnce(() => new Promise(resolve => { finishFinal = resolve; }));
  vi.mocked(api.state).mockRejectedValueOnce(failure === "unavailable" ? new client.AccountFlowError(503, "ACCOUNT_UNAVAILABLE", "private reconciliation text") : new Error("private malformed reconciliation"));
  vi.mocked(api.state).mockResolvedValueOnce(view(purpose, "COMPLETE"));
  mount(); open(purpose); enter(purpose); vi.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" })); await act(async () => {});
  await act(async () => { vi.advanceTimersByTime(299000); });
  finalInputs(); fireEvent.click(screen.getByRole("button", { name: purpose === "register" ? "등록 완료" : "비밀번호 변경" }));
  expect(api[purpose]).toHaveBeenCalledOnce();
  await act(async () => { vi.advanceTimersByTime(1000); });
  expect(vi.mocked(api[purpose]).mock.calls[0][2].aborted).toBe(true);
  expect(screen.getByText(/처리 결과를 확인할 수 없습니다/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "현재 상태 확인" })); await act(async () => {});
  expect(api.state).toHaveBeenCalledOnce();
  expect(screen.queryByRole("button", { name: "새로 시작" })).toBeNull();
  expect(screen.getByText(/처리 결과를 확인할 수 없습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "현재 상태 확인" })).toBeEnabled();
  expect(screen.getByRole("button", { name: purpose === "register" ? "등록 완료" : "비밀번호 변경" })).toBeDisabled();
  expect(screen.getByLabelText("새 비밀번호")).toHaveValue(""); expect(screen.getByLabelText("확인 코드")).toHaveValue("");
  fireEvent.submit(screen.getByLabelText("새 비밀번호").closest("form")!); expect(api[purpose]).toHaveBeenCalledOnce();
  expect(screen.queryByText("private reconciliation text")).toBeNull(); expect(screen.queryByText("private malformed reconciliation")).toBeNull();
  await act(async () => { finishFinal(view(purpose, "COMPLETE")); });
  expect(screen.getByRole("button", { name: "현재 상태 확인" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "TVT 로그인" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "현재 상태 확인" })); await act(async () => {});
  expect(api.state).toHaveBeenCalledTimes(2); expect(api[purpose]).toHaveBeenCalledOnce(); expect(api.start).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "TVT 로그인" })).toBeVisible();
});
it("keeps a thrown final deadline uncertain without turning it into a fresh form", async () => {
  vi.mocked(api.register).mockRejectedValueOnce(new client.AccountFlowError(504, "ACCOUNT_DEADLINE_EXCEEDED", "private vendor text"));
  mount(); open("register"); enter("register"); await sendCode(); finalInputs();
  fireEvent.click(screen.getByRole("button", { name: "등록 완료" }));
  await screen.findByText(/처리 결과를 확인할 수 없습니다/); await act(async () => {});
  expect(screen.getByRole("button", { name: "등록 완료" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "현재 상태 확인" })).toBeEnabled();
  expect(screen.queryByText("private vendor text")).toBeNull();
});
it("local cancellation does not await a nonsettling backend cancel", async () => {
  vi.mocked(api.cancel).mockImplementationOnce(() => new Promise(() => {}));
  mount(); open("recover"); enter("recover"); await sendCode(); finalInputs();
  fireEvent.click(screen.getByRole("button", { name: "취소" }));
  expect(screen.getByLabelText("이메일")).toHaveValue(""); expect(screen.getByLabelText("새 비밀번호")).toHaveValue("");
  expect(screen.getByRole("button", { name: "확인 코드 요청" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "Replacement9!" } });
  expect(api.cancel).toHaveBeenCalledOnce();
});
it("does not let a late final result or finally clear replacement secrets", async () => {
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.register).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  mount(); open("register"); enter("register"); await sendCode(); finalInputs();
  fireEvent.click(screen.getByRole("button", { name: "등록 완료" }));
  fireEvent.change(screen.getByLabelText("이메일"), { target: { value: "replacement@example.test" } });
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "Replacement9!" } });
  await act(async () => { resolve(view("register", "COMPLETE")); });
  expect(screen.getByLabelText("새 비밀번호")).toHaveValue("Replacement9!");
  expect(screen.queryByRole("button", { name: "TVT 로그인" })).toBeNull();
});
it("rejects noncanonical or wrong-signature challenge media without owning a URL", async () => {
  vi.mocked(api.issueCode).mockResolvedValueOnce(view("register", "IMAGE_REQUIRED", { image: { ...image, image_base64: btoa("not a PNG") } }));
  mount(); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findAllByRole("alert"); expect(screen.queryByAltText("계정 확인 이미지")).toBeNull(); expect(URL.createObjectURL).not.toHaveBeenCalled();
});
it("revokes the challenge image and aborts request on source country or purpose replacement", async () => {
  vi.mocked(api.issueCode).mockResolvedValueOnce(view("register", "IMAGE_REQUIRED", { image }));
  mount(); open("register"); enter("register", "phone"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  await screen.findByAltText("계정 확인 이미지");
  const country = screen.getByLabelText("국가 전화 코드") as HTMLSelectElement;
  expect(new Set(Array.from(country.options).map(option => option.value)).size).toBe(197);
  fireEvent.change(country, { target: { value: "US:188" } });
  expect(screen.queryByAltText("계정 확인 이미지")).toBeNull(); expect(revoke).toHaveBeenCalled();
  open("recover"); expect(screen.getByLabelText("새 비밀번호")).toHaveValue("");
});
it("rejects unsupported native password/code characters before latching a final write", async () => {
  mount(); open("register"); enter("register"); await sendCode();
  fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "DemoPass1😀" } });
  fireEvent.change(screen.getByLabelText("확인 코드"), { target: { value: "246810" } });
  fireEvent.click(screen.getByRole("button", { name: "등록 완료" })); await screen.findByRole("alert");
  expect(api.register).not.toHaveBeenCalled(); expect(screen.getByRole("button", { name: "등록 완료" })).toBeEnabled();
});
it("reselecting the current purpose clears inputs and immediately aborts its pending request", async () => {
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.start).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  mount(); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  open("register"); expect(screen.getByLabelText("이메일")).toHaveValue(""); expect(screen.getByRole("button", { name: "확인 코드 요청" })).toBeEnabled();
  await act(async () => { resolve(view("register", "CREATED")); }); expect(api.existence).not.toHaveBeenCalled();
});
it("web logout immediately removes secret controls and fences a late start", async () => {
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.start).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  mount(); open("register"); enter("register"); fireEvent.change(screen.getByLabelText("새 비밀번호"), { target: { value: "DemoPass9!" } });
  fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  const logout = document.createElement("form"); logout.action = "/api/auth/logout"; document.body.append(logout);
  fireEvent.submit(logout); logout.remove(); expect(screen.queryByLabelText("새 비밀번호")).toBeNull();
  await act(async () => { resolve(view("register", "CREATED")); }); expect(api.existence).not.toHaveBeenCalled();
});
it.each([false, true])("TVT profile logout requery removes an in-flight flow (query failure: %s)", async fails => {
  const id = "30000000-0000-4000-8000-000000000001";
  const account = accountClient.accountClient("ui-csrf");
  const profile = { identity_id: id, ...selection, state: "READY" as const, generation: 1, request_id: flow, profile: { account_type: 1, user_name: "", nickname: "", email: "", mobile: "", address: "", no_password: false, avatar_available: false, avatar_url: null } };
  vi.spyOn(accountClient, "accountClient").mockReturnValue({ ...account, profile: vi.fn(async () => profile), logout: vi.fn(async () => ({ identity_id: id, state: "CLOSED" as const, upstream_outcome: "confirmed" as const, request_id: flow })) });
  let resolve!: (value: client.AccountFlowView) => void;
  vi.mocked(api.start).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
  const current = { ...bootstrap, identity: { state: "linked" as const, accounts: [{ id, ...selection }] } };
  render(<SessionBoundary userId="ui-actor" bootstrap={current} csrf="ui-csrf" requery={async () => { if (fails) throw new Error("private authority failure"); return current; }} />);
  await screen.findByRole("button", { name: "TVT 로그아웃" }); open("register"); enter("register"); fireEvent.click(screen.getByRole("button", { name: "확인 코드 요청" }));
  fireEvent.click(screen.getByRole("button", { name: "TVT 로그아웃" })); await act(async () => {});
  if (fails) expect(screen.queryByLabelText("이메일")).toBeNull(); else expect(screen.getByLabelText("이메일")).toHaveValue("");
  await act(async () => { resolve(view("register", "CREATED")); }); expect(api.existence).not.toHaveBeenCalled();
});
