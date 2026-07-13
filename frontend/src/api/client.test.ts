import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScientificReport } from "../types";
import type { LongJobEvent } from "./client";

describe("API client authentication and durable streams", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds the saved bearer token to JSON requests", async () => {
    const request = vi.fn().mockResolvedValue(
      new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", request);
    window.fetch = request;
    const client = await import("./client");
    client.setApiAuthToken("secret-token");

    await client.listSessions();

    const headers = new Headers(request.mock.calls[0][1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer secret-token");
  });

  it("parses a completed scientific job from the SSE stream", async () => {
    const report = { report_id: "r1", title_zh: "报告" };
    const body = `data: ${JSON.stringify({ type: "done", data: { report } })}\n\n`;
    const request = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", request);
    window.fetch = request;
    const client = await import("./client");
    const events: Array<LongJobEvent<ScientificReport>> = [];

    await client.streamScientificAnalysis(
      { session_ids: ["s1"] },
      (event) => events.push(event),
    );

    expect(events).toHaveLength(1);
    expect(events[0].data.report?.report_id).toBe("r1");
  });

  it("propagates consumer errors instead of treating them as malformed SSE", async () => {
    const body = `data: ${JSON.stringify({ type: "error", data: { message: "job failed" } })}\n\n`;
    const request = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", request);
    window.fetch = request;
    const client = await import("./client");

    await expect(
      client.streamScientificAnalysis({ session_ids: ["s1"] }, () => {
        throw new Error("job failed");
      }),
    ).rejects.toThrow("job failed");
  });
});
