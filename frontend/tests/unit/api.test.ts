import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import {
  createThread,
  fetchHealth,
  fetchReadiness,
  getHistory,
  ingestFiles,
  listThreads,
  streamChat,
} from "@/lib/api";

const BACKEND = "http://localhost:8000";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("REST API client", () => {
  it("fetchHealth returns the parsed body", async () => {
    server.use(
      http.get(`${BACKEND}/health`, () => HttpResponse.json({ status: "ok" })),
    );
    const h = await fetchHealth();
    expect(h.status).toBe("ok");
  });

  it("fetchReadiness handles degraded state", async () => {
    server.use(
      http.get(`${BACKEND}/ready`, () =>
        HttpResponse.json({
          status: "degraded",
          ollama: false,
          postgres: true,
          checkpointer: true,
          kb: true,
          detail: "ollama",
        }),
      ),
    );
    const r = await fetchReadiness();
    expect(r.status).toBe("degraded");
    expect(r.ollama).toBe(false);
  });

  it("createThread returns the thread id", async () => {
    server.use(
      http.post(`${BACKEND}/api/threads`, () =>
        HttpResponse.json({ thread_id: "abc-123" }, { status: 201 }),
      ),
    );
    const id = await createThread();
    expect(id).toBe("abc-123");
  });

  it("listThreads returns the array", async () => {
    server.use(
      http.get(`${BACKEND}/api/threads`, () =>
        HttpResponse.json([
          { thread_id: "a", message_count: 2, last_message_at: 1 },
          { thread_id: "b", message_count: 4, last_message_at: 2 },
        ]),
      ),
    );
    const threads = await listThreads();
    expect(threads.map((t) => t.thread_id)).toEqual(["a", "b"]);
  });

  it("getHistory returns role+content pairs", async () => {
    server.use(
      http.get(`${BACKEND}/api/threads/abc/history`, () =>
        HttpResponse.json({
          thread_id: "abc",
          messages: [
            { role: "user", content: "hi" },
            { role: "assistant", content: "hey" },
          ],
        }),
      ),
    );
    const h = await getHistory("abc");
    expect(h.thread_id).toBe("abc");
    expect(h.messages).toHaveLength(2);
  });

  it("ingestFiles posts to /api/ingest and returns the parsed response", async () => {
    let called = false;
    server.use(
      http.post(`${BACKEND}/api/ingest`, ({ request }) => {
        called = true;
        // jsdom's FormData round-tripping through MSW is flaky; we don't need
        // to assert the body content here, just that the call landed.
        expect(request.headers.get("content-type") ?? "").toContain(
          "multipart/form-data",
        );
        return HttpResponse.json({
          ingested_files: 1,
          ingested_chunks: 1,
          memory_ids: ["m0"],
        });
      }),
    );
    const file = new File(["hello"], "note.txt", { type: "text/plain" });
    const r = await ingestFiles([file]);
    expect(called).toBe(true);
    expect(r.ingested_files).toBe(1);
    expect(r.memory_ids).toEqual(["m0"]);
  });
});

describe("streamChat (SSE)", () => {
  it("invokes onToken for token chunks, onThread for the thread event, and onDone", async () => {
    const sseBody =
      `event: message\ndata: ${JSON.stringify({ type: "token", data: "hello " })}\n\n` +
      `event: thread\ndata: ${JSON.stringify({ thread_id: "t1" })}\n\n` +
      `event: message\ndata: ${JSON.stringify({ type: "token", data: "world" })}\n\n` +
      `event: message\ndata: ${JSON.stringify({ type: "done", data: "" })}\n\n`;

    server.use(
      http.post(`${BACKEND}/api/chat`, () =>
        new HttpResponse(sseBody, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );

    const tokens: string[] = [];
    let threadId: string | null = null;
    let done = false;

    await streamChat(
      { message: "hi" },
      {
        onToken: (t) => tokens.push(t),
        onThread: (id) => {
          threadId = id;
        },
        onDone: () => {
          done = true;
        },
      },
    );

    expect(tokens.join("")).toBe("hello world");
    expect(threadId).toBe("t1");
    expect(done).toBe(true);
  });

  it("invokes onError for error chunks", async () => {
    const sseBody =
      `event: message\ndata: ${JSON.stringify({ type: "error", data: "boom" })}\n\n` +
      `event: message\ndata: ${JSON.stringify({ type: "done", data: "" })}\n\n`;
    server.use(
      http.post(`${BACKEND}/api/chat`, () =>
        new HttpResponse(sseBody, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );
    let err: string | null = null;
    await streamChat(
      { message: "hi" },
      {
        onToken: () => {},
        onError: (e) => {
          err = e;
        },
        onDone: () => {},
      },
    );
    expect(err).toBe("boom");
  });
});
