// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { api, streamEvents } from "./api";
import type { Run } from "./types";

vi.mock("./api", () => ({
  api: vi.fn(),
  streamEvents: vi.fn().mockResolvedValue(undefined),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("connects, starts a demo, shows test evidence, and requires review before export", async () => {
  const project = {
    id: "p".repeat(32),
    name: "Checkout total",
    kind: "demo:cart",
    suggested_task:
      "Fix calculate_total: include item quantities and reject discounts outside 0..1.",
  };
  let current: Run = {
    id: "r".repeat(32),
    project_id: project.id,
    task: project.suggested_task,
    status: "awaiting_review",
    attempt: 2,
    tool_calls: 12,
    input_tokens: 0,
    output_tokens: 0,
    elapsed_seconds: 1,
    changed_files: ["src/solution.py"],
    diff: "--- a/src/solution.py\n+++ b/src/solution.py\n+fixed\n",
    tests: [
      {
        attempt: 2,
        exit_code: 0,
        passed: 5,
        failed: 0,
        errors: 0,
        skipped: 0,
        output: "5 passed",
      },
    ],
    error: null,
  };
  vi.mocked(api).mockImplementation(async (path, _token, init) => {
    if (path === "/health")
      return {
        provider: "demo",
        runner: "trusted-demo",
        role: "owner",
      } as never;
    if (path === "/projects" || (path === "/runs" && !init)) return [] as never;
    if (path === "/projects/demo/cart") return project as never;
    if (path.endsWith("/files"))
      return ["src/solution.py", "tests/test_solution.py"] as never;
    if (path.includes("/file?")) return { content: "original code" } as never;
    if (path.endsWith("/review")) {
      current = { ...current, status: "approved" };
      return current as never;
    }
    return current as never;
  });
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Workspace access token"),
    "a-secure-demo-owner-token",
  );
  await user.click(screen.getByRole("button", { name: "Connect" }));
  await user.click(
    await screen.findByRole("button", { name: "Checkout total" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Start engineering run" }),
  );
  expect(await screen.findByText("Patch ready for review")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Download patch" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Test results" }));
  expect(screen.getByText("5 passed", { selector: "pre" })).toBeTruthy();
  await user.click(screen.getByRole("button", { name: "Approve patch" }));
  expect(
    await screen.findByRole("button", { name: "Download patch" }),
  ).toBeTruthy();
  await waitFor(() => expect(streamEvents).toHaveBeenCalled());
  expect(localStorage.length).toBe(0);
});
