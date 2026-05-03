import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { REPORT_STORAGE_KEY, THREAD_STORAGE_KEY, useChatStore } from "@/lib/store";
import type { ReportSessionInspectionResponse } from "@/types";

const BACKEND = "http://localhost:8000";

type InspectionOverrides = Partial<Omit<ReportSessionInspectionResponse, "session">> & {
  session?: Partial<ReportSessionInspectionResponse["session"]>;
};

function makeInspection(
  overrides: InspectionOverrides = {},
): ReportSessionInspectionResponse {
  const sessionId = overrides.session?.session_id ?? "report-123";
  const currentStage =
    overrides.current_stage ?? overrides.session?.current_stage ?? "bootstrap";
  const session = {
    session_id: sessionId,
    status: "blocked",
    current_stage: currentStage,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:03Z",
    last_error: null,
    metadata: {},
    ...overrides.session,
  } satisfies ReportSessionInspectionResponse["session"];

  return {
    current_stage: currentStage,
    stages: [],
    gates: [],
    artifacts: [],
    validation_findings: [],
    exports: [],
    recent_logs: [],
    ...overrides,
    session,
  };
}

const server = setupServer(
  http.get(`${BACKEND}/api/reports/:sessionId`, ({ params }) =>
    HttpResponse.json(
      makeInspection({
        session: { session_id: String(params.sessionId) },
      }),
    ),
  ),
);

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

  it("setActiveView toggles between graph and report", () => {
    expect(useChatStore.getState().activeView).toBe("graph");
    useChatStore.getState().setActiveView("report");
    expect(useChatStore.getState().activeView).toBe("report");
    useChatStore.getState().setActiveView("graph");
    expect(useChatStore.getState().activeView).toBe("graph");
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
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json(
            makeInspection({
              session: { status: "active", current_stage: "bootstrap" },
              stages: [
                {
                  stage_id: "stage-1",
                  session_id: "report-123",
                  name: "bootstrap",
                  status: "complete",
                  started_at: "2024-01-01T00:00:00Z",
                  completed_at: "2024-01-01T00:00:02Z",
                  summary: "Template confirmation gate closed",
                  error: null,
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
                  message: "Report bootstrap gate closed",
                  payload: { gate_id: "gate-1", choice: "cancel" },
                  created_at: "2024-01-01T00:00:02Z",
                },
              ],
            }),
          ),
        ),
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
      expect(useChatStore.getState().activeView).toBe("report");
      expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123");
      expect(useChatStore.getState().reportStatus).toBe("active");
      expect(useChatStore.getState().reportCards.map((card) => card.kind)).toEqual([
        "stage_started",
        "gate_closed",
      ]);
      expect(useChatStore.getState().currentGate).toBeNull();
    });

    it("launchReport only auto-switches the first time the report view opens", async () => {
      const launchResponse = {
        session_id: "report-123",
        status: "blocked",
        current_stage: "bootstrap",
        resumed: false,
      } as const;
      const sseBody = `event: message
data: ${JSON.stringify({ type: "done", data: "" })}

`;
      let launchCount = 0;

      server.use(
        http.post(`${BACKEND}/api/reports`, async ({ request }) => {
          const body = await request.json();
          if (launchCount === 0) {
            expect(body).toEqual({});
          } else {
            expect(body).toEqual({ session_id: "report-123" });
          }
          launchCount += 1;
          return HttpResponse.json(launchResponse);
        }),
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json(
            makeInspection({
              session: { status: "blocked", current_stage: "bootstrap" },
            }),
          ),
        ),
        http.get(`${BACKEND}/api/reports/report-123/stream`, () =>
          new HttpResponse(sseBody, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
        ),
      );

      await useChatStore.getState().launchReport();
      expect(useChatStore.getState().activeView).toBe("report");
      expect(useChatStore.getState().activeReportId).toBe("report-123");

      useChatStore.getState().setActiveView("graph");
      await useChatStore.getState().launchReport();
      expect(useChatStore.getState().activeView).toBe("graph");
      expect(useChatStore.getState().activeReportId).toBe("report-123");
    });

    it("submitReportGateAnswer preserves the gate until the answer succeeds and refreshes inspection", async () => {
      const gate = {
        session_id: "report-123",
        gate_id: "gate-1",
        stage_id: "stage-1",
        question: { gate_id: "gate-1", prompt: "Confirm", options: [] },
        status: "open",
        created_at: "2024-01-01T00:00:01Z",
      } as const;
      let resolveAnswer!: () => void;
      let markAnswerStarted!: () => void;
      const answerStarted = new Promise<void>((resolve) => {
        markAnswerStarted = resolve;
      });
      const answerRelease = new Promise<void>((resolve) => {
        resolveAnswer = resolve;
      });

      server.use(
        http.post(
          `${BACKEND}/api/reports/report-123/gates/gate-1/answer`,
          async ({ request }) => {
            expect(await request.json()).toEqual({
              answer: { choice: "cancel" },
            });
            markAnswerStarted();
            await answerRelease;
            return new HttpResponse(null, { status: 204 });
          },
        ),
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json(
            makeInspection({
              session: { status: "complete", current_stage: "export_report" },
              current_stage: "export_report",
              stages: [
                {
                  stage_id: "stage-export",
                  session_id: "report-123",
                  name: "export_report",
                  status: "complete",
                  started_at: "2024-01-01T00:00:02Z",
                  completed_at: "2024-01-01T00:00:03Z",
                  summary: "PDF export ready",
                  error: null,
                },
              ],
              exports: [
                {
                  export_id: "export-1",
                  session_id: "report-123",
                  status: "ready",
                  format: "pdf",
                  output_path: "/tmp/report.pdf",
                  diagnostics: { pages: 4 },
                  created_at: "2024-01-01T00:00:02Z",
                  completed_at: "2024-01-01T00:00:03Z",
                },
              ],
            }),
          ),
        ),
      );

      useChatStore.setState({
        activeReportId: "report-123",
        currentGate: gate,
      });

      const answerPromise = useChatStore
        .getState()
        .submitReportGateAnswer({ choice: "cancel" });

      await answerStarted;
      expect(useChatStore.getState().currentGate).toMatchObject({ gate_id: "gate-1" });

      resolveAnswer();
      await answerPromise;

      expect(useChatStore.getState().currentGate).toBeNull();
      expect(useChatStore.getState().reportStatus).toBe("complete");
      expect(useChatStore.getState().exports).toEqual([
        expect.objectContaining({ export_id: "export-1", status: "ready" }),
      ]);
    });

    it("submitReportGateAnswer restores the gate and skips refresh when the answer fails", async () => {
      const gate = {
        session_id: "report-123",
        gate_id: "gate-1",
        stage_id: "stage-1",
        question: { gate_id: "gate-1", prompt: "Confirm", options: [] },
        status: "open",
        created_at: "2024-01-01T00:00:01Z",
      } as const;
      let inspectionCalls = 0;

      server.use(
        http.post(`${BACKEND}/api/reports/report-123/gates/gate-1/answer`, () =>
          HttpResponse.json({ detail: "invalid choice" }, { status: 422 }),
        ),
        http.get(`${BACKEND}/api/reports/report-123`, () => {
          inspectionCalls += 1;
          return HttpResponse.json(makeInspection());
        }),
      );

      useChatStore.setState({
        activeReportId: "report-123",
        currentGate: gate,
      });

      await expect(
        useChatStore.getState().submitReportGateAnswer({ choice: "invalid" }),
      ).rejects.toThrow(/HTTP 422/);

      expect(useChatStore.getState().currentGate).toMatchObject({ gate_id: "gate-1" });
      expect(useChatStore.getState().reportError).toContain("HTTP 422");
      expect(inspectionCalls).toBe(0);
    });

    it("launchReport refreshes durable inspection state into the report workspace", async () => {
      const launchResponse = {
        session_id: "report-123",
        status: "blocked",
        current_stage: "bootstrap",
        resumed: false,
      } as const;
      const sseBody = `event: message
data: ${JSON.stringify({ type: "done", data: "" })}

`;

      server.use(
        http.post(`${BACKEND}/api/reports`, () => HttpResponse.json(launchResponse)),
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json(
            makeInspection({
              session: { status: "complete", current_stage: "export_report" },
              current_stage: "export_report",
              stages: [
                {
                  stage_id: "stage-inventory",
                  session_id: "report-123",
                  name: "inventory",
                  status: "complete",
                  started_at: "2024-01-01T00:00:00Z",
                  completed_at: "2024-01-01T00:00:01Z",
                  summary: "Inventory complete",
                  error: null,
                },
                {
                  stage_id: "stage-export",
                  session_id: "report-123",
                  name: "export_report",
                  status: "complete",
                  started_at: "2024-01-01T00:00:02Z",
                  completed_at: "2024-01-01T00:00:03Z",
                  summary: "PDF export ready",
                  error: null,
                },
              ],
              artifacts: [
                {
                  artifact_id: "artifact-plan",
                  session_id: "report-123",
                  stage_id: "stage-inventory",
                  kind: "section_plan",
                  content: { title: "Synthetic section plan" },
                  created_at: "2024-01-01T00:00:01Z",
                },
              ],
              validation_findings: [
                {
                  finding_id: "finding-warning",
                  session_id: "report-123",
                  severity: "warning",
                  code: "W001",
                  message: "Review synthetic evidence coverage",
                  payload: { section: "evidence" },
                  created_at: "2024-01-01T00:00:02Z",
                },
              ],
              exports: [
                {
                  export_id: "export-pdf",
                  session_id: "report-123",
                  status: "ready",
                  format: "pdf",
                  output_path: "/tmp/private/report-final.pdf",
                  diagnostics: { pages: 6 },
                  created_at: "2024-01-01T00:00:02Z",
                  completed_at: "2024-01-01T00:00:03Z",
                },
              ],
              recent_logs: [
                {
                  log_id: "log-export",
                  session_id: "report-123",
                  stage_id: "stage-export",
                  level: "info",
                  message: "Report export_report stage completed",
                  payload: { stage_name: "export_report" },
                  created_at: "2024-01-01T00:00:03Z",
                },
              ],
            }),
          ),
        ),
        http.get(`${BACKEND}/api/reports/report-123/stream`, () =>
          new HttpResponse(sseBody, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
        ),
      );

      await useChatStore.getState().launchReport();

      for (let attempt = 0; attempt < 20; attempt += 1) {
        if (useChatStore.getState().exports.length === 1) break;
        await new Promise((resolve) => setTimeout(resolve, 10));
      }

      expect(useChatStore.getState().reportStatus).toBe("complete");
      expect(useChatStore.getState().stages).toEqual([
        expect.objectContaining({ stage_id: "stage-inventory", status: "complete" }),
        expect.objectContaining({ stage_id: "stage-export", status: "complete" }),
      ]);
      expect(useChatStore.getState().artifacts).toEqual([
        expect.objectContaining({ artifact_id: "artifact-plan", kind: "section_plan" }),
      ]);
      expect(useChatStore.getState().validationFindings).toEqual([
        expect.objectContaining({ finding_id: "finding-warning", severity: "warning" }),
      ]);
      expect(useChatStore.getState().exports).toEqual([
        expect.objectContaining({ export_id: "export-pdf", status: "ready" }),
      ]);
      expect(useChatStore.getState().reportCards).toEqual([
        expect.objectContaining({ kind: "stage_completed", stage_id: "stage-export" }),
      ]);
    });

    it("launchReport records a bounded inspection refresh error without dropping a live gate", async () => {
      const launchResponse = {
        session_id: "report-123",
        status: "blocked",
        current_stage: "bootstrap",
        resumed: false,
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
      const sseBody = `event: message
data: ${JSON.stringify({
        type: "report_gate",
        data: reportGate.question.prompt,
        payload: reportGate,
      })}

`;

      server.use(
        http.post(`${BACKEND}/api/reports`, () => HttpResponse.json(launchResponse)),
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json({ detail: "inspection unavailable" }, { status: 503 }),
        ),
        http.get(`${BACKEND}/api/reports/report-123/stream`, () =>
          new HttpResponse(sseBody, {
            status: 200,
            headers: { "content-type": "text/event-stream" },
          }),
        ),
      );

      await useChatStore.getState().launchReport();

      for (let attempt = 0; attempt < 20; attempt += 1) {
        if (useChatStore.getState().currentGate?.gate_id === "gate-1") break;
        await new Promise((resolve) => setTimeout(resolve, 10));
      }

      expect(useChatStore.getState().currentGate).toMatchObject({ gate_id: "gate-1" });
      expect(useChatStore.getState().reportError).toContain("HTTP 503");
      expect(useChatStore.getState().reportError?.length).toBeLessThanOrEqual(240);
    });

    it("hydrateReportFromStorage tolerates malformed snapshots with missing collections", async () => {
      window.localStorage.setItem(REPORT_STORAGE_KEY, "report-123");

      server.use(
        http.get(`${BACKEND}/api/reports/report-123`, () =>
          HttpResponse.json({
            session: {
              session_id: "report-123",
              status: "failed",
              current_stage: "bootstrap",
              created_at: "2024-01-01T00:00:00Z",
              updated_at: "2024-01-01T00:00:03Z",
              last_error: "pipeline stopped",
              metadata: {},
            },
            current_stage: "bootstrap",
          }),
        ),
      );

      await useChatStore.getState().hydrateReportFromStorage();

      expect(useChatStore.getState().reportStatus).toBe("failed");
      expect(useChatStore.getState().stages).toEqual([]);
      expect(useChatStore.getState().artifacts).toEqual([]);
      expect(useChatStore.getState().validationFindings).toEqual([]);
      expect(useChatStore.getState().exports).toEqual([]);
      expect(useChatStore.getState().currentGate).toBeNull();
      expect(useChatStore.getState().reportError).toBe("pipeline stopped");
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
            artifacts: [
              {
                artifact_id: "artifact-1",
                session_id: "report-123",
                stage_id: "stage-1",
                kind: "section_plan",
                content: { section: "timeline" },
                created_at: "2024-01-01T00:00:00Z",
              },
            ],
            validation_findings: [
              {
                finding_id: "finding-1",
                session_id: "report-123",
                severity: "warning",
                code: "W001",
                message: "Needs review",
                payload: { section: "timeline" },
                created_at: "2024-01-01T00:00:01Z",
              },
            ],
            exports: [
              {
                export_id: "export-1",
                session_id: "report-123",
                status: "ready",
                format: "pdf",
                output_path: "report.pdf",
                diagnostics: { pages: 4 },
                created_at: "2024-01-01T00:00:02Z",
                completed_at: "2024-01-01T00:00:03Z",
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
      expect(useChatStore.getState().activeView).toBe("report");
      expect(useChatStore.getState().reportStatus).toBe("blocked");
      expect(useChatStore.getState().currentGate).toMatchObject({
        gate_id: "gate-1",
        status: "open",
      });
      expect(useChatStore.getState().stages).toEqual([
        expect.objectContaining({
          stage_id: "stage-1",
          name: "bootstrap",
          status: "complete",
        }),
      ]);
      expect(useChatStore.getState().artifacts).toEqual([
        expect.objectContaining({
          artifact_id: "artifact-1",
          kind: "section_plan",
        }),
      ]);
      expect(useChatStore.getState().validationFindings).toEqual([
        expect.objectContaining({
          finding_id: "finding-1",
          severity: "warning",
        }),
      ]);
      expect(useChatStore.getState().exports).toEqual([
        expect.objectContaining({
          export_id: "export-1",
          status: "ready",
        }),
      ]);
      expect(useChatStore.getState().reportCards).toHaveLength(2);
      expect(useChatStore.getState().reportCards.map((card) => card.kind)).toEqual([
        "stage_started",
        "stage_completed",
      ]);
      expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123");
    });
  });
});
