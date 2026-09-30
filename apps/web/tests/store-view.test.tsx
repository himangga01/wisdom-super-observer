// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { StoresView } from "../src/components/stores-view";
afterEach(cleanup);
it("provides keyboard accessible tenant and store navigation", () => {
  render(<StoresView memberships={[{ tenant_id: "tenant-a", role: "owner" }, { tenant_id: "tenant-b", role: "staff" }]} tenantId="tenant-a" stores={[{ id: "store-a", tenant_id: "tenant-a", name: "강남점", timezone: "Asia/Seoul", active: true }]} csrf="csrf" />);
  expect(screen.getByLabelText("조직 선택")).toBeVisible();
  expect(screen.getByRole("link", { name: /강남점/ })).toHaveAttribute("href", "/stores/store-a?tenant_id=tenant-a");
  expect(screen.getByRole("button", { name: "로그아웃" })).toBeVisible();
});
it("shows empty authorization without inventing stores", () => {
  render(<StoresView memberships={[]} stores={[]} csrf="csrf" />);
  expect(screen.getByRole("status")).toHaveTextContent("접근할 수 있는 매장이 없습니다");
  expect(screen.queryByRole("link", { name: /매장 열기/ })).toBeNull();
});
