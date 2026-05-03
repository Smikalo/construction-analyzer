import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import {
  answerReportGate,
  createOrResumeReportSession,
  createThread,
  fetchHealth,
  fetchReadiness,
  getHistory,
  getReportSession,
  ingestFiles,
  listThreads,
  streamChat,
  streamReportSession,
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
      http.post(`${BACKEND}/api/ingest`, () => {
        called = true;
        // jsdom's FormData round-tripping through MSW is flaky; we don't need
        // to assert the body content here, just that the call landed.
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
  it("createOrResumeReportSession returns the parsed launch response", async () => {
    server.use(
      http.post(`${BACKEND}/api/reports`, async ({ request }) => {
        expect(await request.json()).toEqual({
          session_id: "report-123",
          thread_id: "thread-9",
          metadata: { source: "chat" },
        });
        return HttpResponse.json({
          session_id: "report-123",
          status: "blocked",
          current_stage: "bootstrap",
          resumed: false,
        });
      }),
    );

    const response = await createOrResumeReportSession({
      session_id: "report-123",
      thread_id: "thread-9",
      metadata: { source: "chat" },
    });

    expect(response).toEqual({
      session_id: "report-123",
      status: "blocked",
      current_stage: "bootstrap",
      resumed: false,
    });
  });

  it("getReportSession returns the inspection payload", async () => {
    server.use(
      http.get(`${BACKEND}/api/reports/report-123`, () =>
        HttpResponse.json({
          session: {
            session_id: "report-123",
            status: "blocked",
            current_stage: "bootstrap",
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:01Z",
            last_error: null,
            metadata: {},
          },
          current_stage: "bootstrap",
          stages: [],
          gates: [],
          recent_logs: [],
        }),
      ),
    );

    const response = await getReportSession("report-123");
    expect(response.session.session_id).toBe("report-123");
    expect(response.current_stage).toBe("bootstrap");
  });

  it("answerReportGate posts the answer payload", async () => {
    let body: unknown = null;
    server.use(
      http.post(
        `${BACKEND}/api/reports/report-123/gates/gate-1/answer`,
        async ({ request }) => {
          body = await request.json();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    await expect(
      answerReportGate("report-123", "gate-1", { choice: "cancel" }),
    ).resolves.toBeUndefined();
    expect(body).toEqual({ answer: { choice: "cancel" } });
  });

  it("streamReportSession dispatches report cards and gates", async () => {
    const reportCard = {
      session_id: "report-123",
      stage_id: "stage-1",
      stage_name: "bootstrap",
      kind: "stage_started",
      message: "Bootstrap stage started",
      created_at: "2024-01-01T00:00:00Z",
      payload: { stage_name: "bootstrap" },
    } as const;
    const reportGate = {
      session_id: "report-123",
      gate_id: "report_template_confirmation",
      stage_id: "stage-1",
      question: {
        gate_id: "report_template_confirmation",
        prompt: "Confirm the report template for this session.",
        options: [],
      },
      status: "open",
      created_at: "2024-01-01T00:00:01Z",
    } as const;

    const sseBody =
      `event: message\ndata: ${JSON.stringify({
        type: "report_card",
        data: reportCard.message,
        payload: reportCard,
      })}\n\n` +
      `event: message\ndata: ${JSON.stringify({
        type: "report_gate",
        data: reportGate.question.prompt,
        payload: reportGate,
      })}\n\n` +
      `event: message\ndata: ${JSON.stringify({ type: "done", data: "" })}\n\n`;

    server.use(
      http.get(`${BACKEND}/api/reports/report-123/stream`, () =>
        new HttpResponse(sseBody, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        }),
      ),
    );

    const cards: typeof reportCard[] = [];
    const gates: typeof reportGate[] = [];
    let done = false;

    await streamReportSession("report-123", {
      onReportCard: (card) => cards.push(card),
      onReportGate: (gate) => gates.push(gate),
      onDone: () => {
        done = true;
      },
    });

    expect(cards).toEqual([reportCard]);
    expect(gates).toEqual([reportGate]);
    expect(done).toBe(true);
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
