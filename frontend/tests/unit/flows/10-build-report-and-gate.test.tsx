import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const apiMocks = vi.hoisted(() => ({
  createOrResumeReportSession: vi.fn(),
  streamReportSession: vi.fn(),
  answerReportGate: vi.fn(),
  getReportSession: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    createOrResumeReportSession: apiMocks.createOrResumeReportSession,
    streamReportSession: apiMocks.streamReportSession,
    answerReportGate: apiMocks.answerReportGate,
    getReportSession: apiMocks.getReportSession,
  };
});

describe("Build Report flow", () => {
  let ChatPanel: typeof import("@/components/chat/ChatPanel").ChatPanel;
  let REPORT_STORAGE_KEY: string;
  let useChatStore: typeof import("@/lib/store").useChatStore;

  beforeEach(async () => {
    vi.resetModules();
    ({ ChatPanel } = await import("@/components/chat/ChatPanel"));
    ({ REPORT_STORAGE_KEY, useChatStore } = await import("@/lib/store"));

    useChatStore.getState().reset();
    window.localStorage.clear();

    apiMocks.createOrResumeReportSession.mockReset();
    apiMocks.streamReportSession.mockReset();
    apiMocks.answerReportGate.mockReset();
    apiMocks.getReportSession.mockReset();

    useChatStore.setState({
      hydrateReportFromStorage: vi.fn().mockResolvedValue(undefined),
    } as never);

    apiMocks.createOrResumeReportSession.mockResolvedValue({
      session_id: "report-123",
      status: "blocked",
      current_stage: "bootstrap",
      resumed: false,
    });

    apiMocks.streamReportSession.mockImplementation(async (_sessionId, callbacks) => {
      callbacks.onReportCard?.({
        session_id: "report-123",
        stage_id: "stage-bootstrap",
        stage_name: "bootstrap",
        kind: "stage_started",
        message: "Bootstrap stage started",
        created_at: "2024-01-01T00:00:00Z",
        payload: { stage_name: "bootstrap" },
      });

      callbacks.onReportGate?.({
        session_id: "report-123",
        gate_id: "template_confirmation",
        stage_id: "stage-bootstrap",
        question: {
          question_id: "template_confirmation",
          label: "Confirm the report template for this session.",
          options: [
            { value: "general_project_dossier", label: "General project dossier" },
            { value: "site_safety_packet", label: "Site safety packet" },
          ],
        },
        status: "open",
        created_at: "2024-01-01T00:00:01Z",
      });
    });

    let gateAnswered = false;
    apiMocks.answerReportGate.mockImplementation(async () => {
      gateAnswered = true;
    });
    apiMocks.getReportSession.mockImplementation(async () => ({
      session: {
        session_id: "report-123",
        status: gateAnswered ? "complete" : "blocked",
        current_stage: "bootstrap",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:03Z",
        last_error: null,
        metadata: {},
      },
      current_stage: "bootstrap",
      stages: [
        {
          stage_id: "stage-bootstrap",
          session_id: "report-123",
          name: "bootstrap",
          status: gateAnswered ? "complete" : "active",
          started_at: "2024-01-01T00:00:00Z",
          completed_at: gateAnswered ? "2024-01-01T00:00:03Z" : null,
          summary: gateAnswered ? "Template accepted" : null,
          error: null,
        },
      ],
      gates: gateAnswered
        ? []
        : [
            {
              gate_id: "template_confirmation",
              session_id: "report-123",
              stage_id: "stage-bootstrap",
              status: "open",
              question: {
                question_id: "template_confirmation",
                label: "Confirm the report template for this session.",
                options: [
                  { value: "general_project_dossier", label: "General project dossier" },
                  { value: "site_safety_packet", label: "Site safety packet" },
                ],
              },
              answer: {},
              created_at: "2024-01-01T00:00:01Z",
              closed_at: null,
            },
          ],
      artifacts: [],
      validation_findings: [],
      exports: [],
      recent_logs: [
        {
          log_id: "log-bootstrap-started",
          session_id: "report-123",
          stage_id: "stage-bootstrap",
          level: "info",
          message: "Report bootstrap stage started",
          payload: { stage_name: "bootstrap" },
          created_at: "2024-01-01T00:00:00Z",
        },
      ],
    }));
  });

  it("launches a report session, renders streamed cards and gates, and submits the gate answer", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    const buildButton = screen.getByRole("button", { name: /build report/i });
    expect(buildButton).toBeEnabled();

    fireEvent.click(buildButton);

    await waitFor(() =>
      expect(apiMocks.createOrResumeReportSession).toHaveBeenCalledWith({}),
    );
    await waitFor(() =>
      expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123"),
    );

    expect(apiMocks.streamReportSession).toHaveBeenCalledWith(
      "report-123",
      expect.objectContaining({
        onReportCard: expect.any(Function),
        onReportGate: expect.any(Function),
      }),
    );

    expect(await screen.findByRole("article", { name: /stage started/i })).toBeInTheDocument();
    expect(screen.getByText("Stage started")).toBeInTheDocument();
    expect(screen.getByText("Bootstrap stage started")).toBeInTheDocument();

    const gateGroup = await screen.findByRole("group", {
      name: "Confirm the report template for this session.",
    });
    expect(gateGroup).toBeInTheDocument();
    expect(screen.getByLabelText("General project dossier")).toBeInTheDocument();
    expect(screen.getByLabelText("Site safety packet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /build report/i })).toBeDisabled();

    await user.click(screen.getByLabelText("General project dossier"));
    await user.click(screen.getByRole("button", { name: /submit/i }));

    await waitFor(() =>
      expect(apiMocks.answerReportGate).toHaveBeenCalledWith(
        "report-123",
        "template_confirmation",
        {
          question_id: "template_confirmation",
          value: "general_project_dossier",
        },
      ),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("group", {
          name: "Confirm the report template for this session.",
        }),
      ).not.toBeInTheDocument(),
    );
  });
});
