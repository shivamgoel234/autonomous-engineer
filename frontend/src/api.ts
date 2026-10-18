import type { AgentEvent } from "./types";

export async function api<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...init.headers },
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: response.statusText }));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Request validation failed",
    );
  }
  return response.json() as Promise<T>;
}

// Fetch streaming supports authorization headers. Native EventSource does not.
export async function streamEvents(
  runId: string,
  token: string,
  after: number,
  signal: AbortSignal,
  onEvent: (event: AgentEvent) => void,
) {
  const response = await fetch(`/api/v1/runs/${runId}/events?after=${after}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok || !response.body)
    throw new Error("Could not connect to the run timeline");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = block
          .split("\n")
          .find((line) => line.startsWith("data: "));
        if (data && !block.includes("event: done"))
          onEvent(JSON.parse(data.slice(6)) as AgentEvent);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
