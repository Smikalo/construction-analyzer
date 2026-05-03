import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

function openGateInspection() {
  return {
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
    stages: [
      {
        stage_id: "stage-bootstrap",
        session_id: "report-123",
        name: "bootstrap",
        status: "active",
        started_at: "2024-01-01T00:00:00Z",
        completed_at: null,
        summary: null,
        error: null,
      },
    ],
    gates: [
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
  };
}

function completedInspection() {
  return {
    session: {
      session_id: "report-123",
      status: "complete",
      current_stage: "export_report",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:09Z",
      last_error: null,
      metadata: {},
    },
    current_stage: "export_report",
    stages: [
      {
        stage_id: "stage-bootstrap",
        session_id: "report-123",
        name: "bootstrap",
        status: "complete",
        started_at: "2024-01-01T00:00:00Z",
        completed_at: "2024-01-01T00:00:02Z",
        summary: "Template accepted",
        error: null,
      },
      {
        stage_id: "stage-inventory",
        session_id: "report-123",
        name: "inventory",
        status: "complete",
        started_at: "2024-01-01T00:00:02Z",
        completed_at: "2024-01-01T00:00:04Z",
        summary: "Evidence inventory complete",
        error: null,
      },
      {
        stage_id: "stage-validation",
        session_id: "report-123",
        name: "validate_report",
        status: "complete",
        started_at: "2024-01-01T00:00:04Z",
        completed_at: "2024-01-01T00:00:06Z",
        summary: "Validation complete with warnings",
        error: null,
      },
      {
        stage_id: "stage-export",
        session_id: "report-123",
        name: "export_report",
        status: "complete",
        started_at: "2024-01-01T00:00:06Z",
        completed_at: "2024-01-01T00:00:09Z",
        summary: "PDF export ready",
        error: null,
      },
    ],
    gates: [],
    artifacts: [
      {
        artifact_id: "section-plan",
        session_id: "report-123",
        stage_id: "stage-inventory",
        kind: "section_plan",
        content: { title: "Synthetic report structure" },
        created_at: "2024-01-01T00:00:04Z",
      },
      {
        artifact_id: "section-draft",
        session_id: "report-123",
        stage_id: "stage-validation",
        kind: "section_draft",
        content: { title: "Validated synthetic draft" },
        created_at: "2024-01-01T00:00:06Z",
      },
    ],
    validation_findings: [
      {
        finding_id: "finding-warning",
        session_id: "report-123",
        severity: "warning",
        code: "SYN-WARN",
        message: "Synthetic evidence should be reviewed before signing.",
        payload: { section: "Evidence" },
        created_at: "2024-01-01T00:00:06Z",
      },
      {
        finding_id: "finding-info",
        session_id: "report-123",
        severity: "info",
        code: "SYN-INFO",
        message: "Synthetic export diagnostics are available.",
        payload: { pages: 6 },
        created_at: "2024-01-01T00:00:07Z",
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
        created_at: "2024-01-01T00:00:07Z",
        completed_at: "2024-01-01T00:00:09Z",
      },
    ],
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
      {
        log_id: "log-bootstrap-closed",
        session_id: "report-123",
        stage_id: "stage-bootstrap",
        level: "info",
        message: "Report bootstrap gate closed",
        payload: { gate_id: "template_confirmation" },
        created_at: "2024-01-01T00:00:02Z",
      },
      {
        log_id: "log-export-complete",
        session_id: "report-123",
        stage_id: "stage-export",
        level: "info",
        message: "Report export_report stage completed",
        payload: { stage_name: "export_report", exports: 1 },
        created_at: "2024-01-01T00:00:09Z",
      },
    ],
  };
}

describe("Report full path flow", () => {
  let AppShell: typeof import("@/components/shell/AppShell").AppShell;
  let useChatStore: typeof import("@/lib/store").useChatStore;

  beforeEach(async () => {
    vi.resetModules();
    ({ AppShell } = await import("@/components/shell/AppShell"));
    ({ useChatStore } = await import("@/lib/store"));

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
    apiMocks.getReportSession.mockImplementation(async () =>
      gateAnswered ? completedInspection() : openGateInspection(),
    );
  });

  it("keeps chat gates and the center report workspace synchronized from inspection snapshots", async () => {
    const user = userEvent.setup();

    render(<AppShell />);

    await screen.findByTestId("graph-view");

    await user.click(screen.getByRole("button", { name: /build report/i }));

    await screen.findByTestId("report-view");
    expect(await screen.findByRole("article", { name: /stage started/i })).toBeInTheDocument();
    expect(screen.getByText("Bootstrap stage started")).toBeInTheDocument();

    const gateGroup = await screen.findByRole("group", {
      name: "Confirm the report template for this session.",
    });
    expect(gateGroup).toBeInTheDocument();
    expect(screen.getByTestId("current-gate-banner")).toHaveTextContent(
      "Answer the open gate in chat to continue",
    );

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

    expect(screen.getByTestId("report-status-badge")).toHaveTextContent("complete");
    expect(screen.getByTestId("report-current-stage")).toHaveTextContent("export_report");
    expect(screen.getByTestId("report-stage-stage-export")).toHaveAttribute(
      "data-status",
      "complete",
    );
    expect(screen.getByTestId("report-artifact-section-plan")).toHaveTextContent(
      "Synthetic report structure",
    );

    const warningGroup = screen.getByTestId("validation-group-warning");
    expect(within(warningGroup).getByText("Warnings")).toBeInTheDocument();
    expect(
      within(warningGroup).getByText("Synthetic evidence should be reviewed before signing."),
    ).toBeInTheDocument();

    const exportCard = screen.getByTestId("report-export-export-pdf");
    expect(within(exportCard).getByText("ready")).toBeInTheDocument();
    expect(within(exportCard).getByText("Output path: report-final.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/\/tmp\/private\/report-final\.pdf/)).not.toBeInTheDocument();
  });
});
