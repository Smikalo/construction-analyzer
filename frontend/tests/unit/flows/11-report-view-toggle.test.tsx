import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

describe("Report workspace toggle flow", () => {
  let AppShell: typeof import("@/components/shell/AppShell").AppShell;
  let REPORT_STORAGE_KEY: string;
  let useChatStore: typeof import("@/lib/store").useChatStore;

  beforeEach(async () => {
    vi.resetModules();
    ({ AppShell } = await import("@/components/shell/AppShell"));
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
      current_stage: "inventory",
      resumed: false,
    });

    apiMocks.streamReportSession.mockImplementation(async (_sessionId, callbacks) => {
      callbacks.onReportCard?.({
        session_id: "report-123",
        stage_id: "stage-inventory",
        stage_name: "Inventory",
        kind: "stage_started",
        message: "Inventory stage started",
        created_at: "2024-01-01T09:00:00Z",
        payload: { stage_name: "Inventory" },
      });

      callbacks.onReportGate?.({
        session_id: "report-123",
        gate_id: "gate-1",
        stage_id: "stage-inventory",
        question: {
          question_id: "gate-1",
          label: "Review the next section",
          options: [{ value: "continue", label: "Continue" }],
        },
        status: "open",
        created_at: "2024-01-01T09:01:00Z",
      });
    });

    apiMocks.answerReportGate.mockResolvedValue(undefined);
    apiMocks.getReportSession.mockResolvedValue({
      session: {
        session_id: "report-123",
        status: "blocked",
        current_stage: "inventory",
        created_at: "2024-01-01T09:00:00Z",
        updated_at: "2024-01-01T09:01:00Z",
        last_error: null,
        metadata: {},
      },
      current_stage: "inventory",
      stages: [
        {
          stage_id: "stage-inventory",
          session_id: "report-123",
          name: "Inventory",
          status: "active",
          started_at: "2024-01-01T09:00:00Z",
          completed_at: null,
          summary: null,
          error: null,
        },
      ],
      gates: [
        {
          gate_id: "gate-1",
          session_id: "report-123",
          stage_id: "stage-inventory",
          status: "open",
          question: {
            question_id: "gate-1",
            label: "Review the next section",
            options: [{ value: "continue", label: "Continue" }],
          },
          answer: {},
          created_at: "2024-01-01T09:01:00Z",
          closed_at: null,
        },
      ],
      artifacts: [],
      validation_findings: [],
      exports: [],
      recent_logs: [
        {
          log_id: "log-inventory-started",
          session_id: "report-123",
          stage_id: "stage-inventory",
          level: "info",
          message: "Report Inventory stage started",
          payload: { stage_name: "Inventory" },
          created_at: "2024-01-01T09:00:00Z",
        },
      ],
    });
  });

  it("swaps between graph and report workspaces from the chat launch and activity bar controls", async () => {
    const user = userEvent.setup();

    render(<AppShell />);

    await screen.findByTestId("graph-view");
    expect(screen.queryByTestId("report-view")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "bob-graph" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "bob-report" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /build report/i }));

    await waitFor(() =>
      expect(apiMocks.createOrResumeReportSession).toHaveBeenCalledWith({}),
    );
    await waitFor(() =>
      expect(apiMocks.streamReportSession).toHaveBeenCalledWith(
        "report-123",
        expect.objectContaining({
          onReportCard: expect.any(Function),
          onReportGate: expect.any(Function),
        }),
      ),
    );

    const reportView = await screen.findByTestId("report-view");
    expect(reportView).toBeInTheDocument();
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "bob-report" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "bob-report" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /build report/i })).toBeDisabled();
    expect(window.localStorage.getItem(REPORT_STORAGE_KEY)).toBe("report-123");

    await user.click(screen.getByRole("button", { name: "bob-graph" }));

    await screen.findByTestId("graph-view");
    await waitFor(() =>
      expect(screen.queryByTestId("report-view")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "bob-graph" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "bob-report" }));

    await screen.findByTestId("report-view");
    expect(screen.queryByTestId("graph-view")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "bob-report" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});
