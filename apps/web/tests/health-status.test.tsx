// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { HealthStatus } from "../src/components/health-status";

afterEach(cleanup);

describe("HealthStatus", () => {
  it("shows the service as available when liveness responds ok", () => {
    render(<HealthStatus health={{ status: "ok" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("서비스 연결됨");
  });

  it("shows a recoverable unavailable state when liveness cannot be read", () => {
    render(<HealthStatus health={{ status: "unavailable" }} />);

    expect(screen.getByRole("status")).toHaveTextContent("서비스 연결 확인 불가");
  });
});
