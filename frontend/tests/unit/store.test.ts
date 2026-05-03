import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { REPORT_STORAGE_KEY, THREAD_STORAGE_KEY, useChatStore } from "@/lib/store";

const BACKEND = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("useChatStore", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    window.localStorage.clear();
  });

  it("starts with no messages and no thread", () => {
    const s = useChatStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.threadId).toBeNull();
  });

  it("appendUserMessage adds a user message and returns its id", () => {
    const id = useChatStore.getState().appendUserMessage("hello");
    const s = useChatStore.getState();
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0]).toMatchObject({ id, role: "user", content: "hello" });
  });

  it("startAssistantMessage creates a pending assistant message", () => {
    const id = useChatStore.getState().startAssistantMessage();
    const m = useChatStore.getState().messages[0];
    expect(m).toMatchObject({ id, role: "assistant", content: "", pending: true });
  });

  it("appendAssistantToken accumulates tokens onto the pending assistant message", () => {
    const id = useChatStore.getState().startAssistantMessage();
    useChatStore.getState().appendAssistantToken(id, "hello ");
    useChatStore.getState().appendAssistantToken(id, "world");
    const m = useChatStore.getState().messages[0];
    expect(m.content).toBe("hello world");
  });

  it("finishAssistantMessage clears the pending flag", () => {
    const id = useChatStore.getState().startAssistantMessage();
    useChatStore.getState().appendAssistantToken(id, "done");
    useChatStore.getState().finishAssistantMessage(id);
    expect(useChatStore.getState().messages[0].pending).toBeFalsy();
  });

  describe("thread persistence", () => {
    it("setThreadId persists to localStorage", () => {
      useChatStore.getState().setThreadId("abc-123");
      expect(useChatStore.getState().threadId).toBe("abc-123");
      expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBe("abc-123");
    });

    it("hydrateThreadIdFromStorage reads localStorage", () => {
      window.localStorage.setItem(THREAD_STORAGE_KEY, "stored-thread");
      useChatStore.getState().hydrateThreadIdFromStorage();
      expect(useChatStore.getState().threadId).toBe("stored-thread");
    });

    it("clearThread wipes both messages and the persisted thread id", () => {
      useChatStore.getState().setThreadId("abc");
      useChatStore.getState().appendUserMessage("hi");
      useChatStore.getState().clearThread();
      expect(useChatStore.getState().messages).toEqual([]);
      expect(useChatStore.getState().threadId).toBeNull();
      expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  describe("hydrateMessagesFromHistory", () => {
    it("replaces current messages with the provided history", () => {
      useChatStore.getState().appendUserMessage("stale");
      useChatStore.getState().hydrateMessagesFromHistory([
        { role: "user", content: "real first" },
        { role: "assistant", content: "real reply" },
      ]);
      const msgs = useChatStore.getState().messages;
      expect(msgs.map((m) => [m.role, m.content])).toEqual([
        ["user", "real first"],
        ["assistant", "real reply"],
      ]);
    });
  });

  describe("status", () => {
    it("setStatus reflects connectivity", () => {
      useChatStore.getState().setStatus("ready");
      expect(useChatStore.getState().status).toBe("ready");
      useChatStore.getState().setStatus("degraded");
      expect(useChatStore.getState().status).toBe("degraded");
    });
  });

  describe("report sessions", () => {
    it("launchReport stores the report id and appends streamed cards", async () => {
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
        gate_id: "gate-1",
        stage_id: "stage-1",
        question: {
          gate_id: "gate-1",
          prompt: "Confirm the report template for this session.",
          options: [],
        },
        status: "open",
        created_at: "2024-01-01T00:00:01Z",
      } as const;
      const gateClosedCard = {
        session_id: "report-123",
        stage_id: "stage-1",
        stage_name: "bootstrap",
        kind: "gate_closed",
        message: "Template confirmation gate closed",
        created_at: "2024-01-01T00:00:02Z",
        payload: { gate_id: "gate-1", choice: "cancel" },
      } as const;
      const launchResponse = {
        session_id: "report-123",
        status: "blocked",
        current_stage: "bootstrap",
        resumed: false,
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
        `event: message\ndata: ${JSON.stringify({
          type: "report_card",
          data: gateClosedCard.message,
          payload: gateClosedCard,
        })}\n\n` +
        `event: message\ndata: ${JSON.stringify({ type: "done", data: "" })}\n\n`;

      server.use(
        http.post(`${BACKEND}/api/reports`, async ({ request }) => {
          expect(await request.json()).toEqual({});
          return HttpResponse.json(launchResponse);
        }),
        http.get(`${BACKEND}/api/reports/report-123/stream`, () =>
          new HttpResponse(sseBody, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
        ),
      );

      const launch = await useChatStore.getState().launchReport();

      for (let attempt = 0; attempt < 20; attempt += 1) {
        if (
          useChatStore.getState().reportCards.length === 2 &&
          useChatStore.getState().currentGate === null
        ) {
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 10));
      }

      expect(launch).toEqual(launchResponse);
      expect(useChatStore.getState().activeReportId).toBe("report-123");
      expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123");
      expect(useChatStore.getState().reportStatus).toBe("active");
      expect(useChatStore.getState().reportCards.map((card) => card.kind)).toEqual([
        "stage_started",
        "gate_closed",
      ]);
      expect(useChatStore.getState().currentGate).toBeNull();
    });

    it("submitReportGateAnswer clears the gate before posting the answer", async () => {
      const gate = {
        session_id: "report-123",
        gate_id: "gate-1",
        stage_id: "stage-1",
        question: { gate_id: "gate-1", prompt: "Confirm", options: [] },
        status: "open",
        created_at: "2024-01-01T00:00:01Z",
      } as const;

      server.use(
        http.post(
          `${BACKEND}/api/reports/report-123/gates/gate-1/answer`,
          async ({ request }) => {
            expect(await request.json()).toEqual({
              answer: { choice: "cancel" },
            });
            return new HttpResponse(null, { status: 204 });
          },
        ),
      );

      useChatStore.setState({
        activeReportId: "report-123",
        currentGate: gate,
      });

      const answerPromise = useChatStore
        .getState()
        .submitReportGateAnswer({ choice: "cancel" });

      expect(useChatStore.getState().currentGate).toBeNull();
      await answerPromise;
    });

    it("hydrateReportFromStorage rebuilds report state from storage", async () => {
      window.localStorage.setItem(REPORT_STORAGE_KEY, "report-123");

      server.use(
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json({
            session: {
              session_id: "report-123",
              status: "blocked",
              current_stage: "bootstrap",
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:03Z",
              last_error: null,
              metadata: {},
            },
            current_stage: "bootstrap",
            stages: [
              {
                stage_id: "stage-1",
                session_id: "report-123",
                name: "bootstrap",
                status: "complete",
                started_at: "2024-01-01T00:00:00Z",
                completed_at: "2024-01-01T00:00:02Z",
                summary: "Template confirmation gate opened",
                error: null,
              },
            ],
            gates: [
              {
                gate_id: "gate-1",
                session_id: "report-123",
                stage_id: "stage-1",
                status: "open",
                question: {
                  gate_id: "gate-1",
                  prompt: "Confirm the report template for this session.",
                  options: [],
                },
                answer: {},
                created_at: "2024-01-01T00:00:01Z",
                closed_at: null,
              },
            ],
            recent_logs: [
              {
                log_id: "log-1",
                session_id: "report-123",
                stage_id: "stage-1",
                level: "info",
                message: "Report bootstrap stage started",
                payload: { stage_name: "bootstrap" },
                created_at: "2024-01-01T00:00:00Z",
              },
              {
                log_id: "log-2",
                session_id: "report-123",
                stage_id: "stage-1",
                level: "info",
                message: "Report template confirmation gate opened",
                payload: { gate_id: "gate-1" },
                created_at: "2024-01-01T00:00:01Z",
              },
              {
                log_id: "log-3",
                session_id: "report-123",
                stage_id: "stage-1",
                level: "info",
                message: "Report bootstrap stage completed",
                payload: { gate_id: "gate-1" },
                created_at: "2024-01-01T00:00:02Z",
              },
            ],
          }),
        ),
      );

      await useChatStore.getState().hydrateReportFromStorage();

      expect(useChatStore.getState().activeReportId).toBe("report-123");
      expect(useChatStore.getState().reportStatus).toBe("blocked");
      expect(useChatStore.getState().currentGate).toMatchObject({
        gate_id: "gate-1",
        status: "open",
      });
      expect(useChatStore.getState().reportCards).toHaveLength(2);
      expect(useChatStore.getState().reportCards.map((card) => card.kind)).toEqual([
        "stage_started",
        "stage_completed",
      ]);
      expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123");
    });
  });
});
