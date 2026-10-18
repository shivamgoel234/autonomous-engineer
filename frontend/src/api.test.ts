import { afterEach, describe, expect, it, vi } from "vitest";
import { api, streamEvents } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("API and event transport", () => {
  it("authenticates requests and reports server errors", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Owner role required" }), {
          status: 403,
        }),
      );
    await expect(api("/projects", "reviewer-token")).rejects.toThrow(
      "Owner role required",
    );
    expect(fetchMock.mock.calls[0][1]?.headers).toEqual({
      Authorization: "Bearer reviewer-token",
    });
  });
  it("handles event records split across chunks and skips terminal control messages", async () => {
    const chunks = [
      "id: 7\nda",
      'ta: {"id":7,"message":"test passed"}\n\n: heartbeat\n\n',
      "event: done\ndata: {}\n\n",
    ];
    const stream = new ReadableStream({
      start(controller) {
        for (const chunk of chunks)
          controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    });
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(stream));
    const onEvent = vi.fn();
    await streamEvents(
      "run-id",
      "owner-token",
      6,
      new AbortController().signal,
      onEvent,
    );
    expect(onEvent).toHaveBeenCalledExactlyOnceWith({
      id: 7,
      message: "test passed",
    });
    expect(fetchMock.mock.calls[0][0]).toContain("after=6");
  });
});
