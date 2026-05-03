import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ReportView } from "@/components/report/ReportView";
import { useChatStore } from "@/lib/store";

describe("ReportView", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    window.localStorage.clear();
  });

  it("renders the live report projection with stages, gate, sections, findings, and exports", () => {
    useChatStore.setState({
      activeReportId: "report-17",
      activeView: "report",
      reportStatus: "blocked",
      reportError: null,
      currentGate: {
        session_id: "report-17",
        gate_id: "gate-1",
        stage_id: "stage-inventory",
        question: {
          question_id: "gate-1",
          label: "Review the next section",
          options: [],
        },
        status: "open",
        created_at: "2024-01-01T09:01:00Z",
      },
      reportCards: [
        {
          session_id: "report-17",
          stage_id: "stage-inventory",
          stage_name: "Inventory",
          kind: "stage_started",
          message: "Inventory stage started",
          created_at: "2024-01-01T09:00:00Z",
          payload: { stage_name: "Inventory" },
        },
        {
          session_id: "report-17",
          stage_id: "stage-inventory",
          stage_name: "Inventory",
          kind: "gate_opened",
          message: "Inventory gate opened",
          created_at: "2024-01-01T09:01:00Z",
          payload: { gate_id: "gate-1" },
        },
      ],
      stages: [
        {
          stage_id: "stage-inventory",
          session_id: "report-17",
          name: "Inventory",
          status: "active",
          started_at: "2024-01-01T09:00:00Z",
          completed_at: null,
          summary: null,
          error: null,
        },
        {
          stage_id: "stage-review",
          session_id: "report-17",
          name: "Review",
          status: "complete",
          started_at: "2024-01-01T08:00:00Z",
          completed_at: "2024-01-01T08:45:00Z",
          summary: "Done",
          error: null,
        },
      ],
      artifacts: [
        {
          artifact_id: "artifact-plan",
          session_id: "report-17",
          stage_id: "stage-inventory",
          kind: "section_plan",
          content: { title: "Foundation survey" },
          created_at: "2024-01-01T09:02:00Z",
        },
        {
          artifact_id: "artifact-other",
          session_id: "report-17",
          stage_id: "stage-inventory",
          kind: "other",
          content: { title: "Ignore me" },
          created_at: "2024-01-01T09:03:00Z",
        },
      ],
      validationFindings: [
        {
          finding_id: "finding-warning",
          session_id: "report-17",
          severity: "warning",
          code: "W001",
          message: "Needs review",
          payload: { section: "foundation" },
          created_at: "2024-01-01T09:04:00Z",
        },
        {
          finding_id: "finding-blocker",
          session_id: "report-17",
          severity: "blocker",
          code: "B007",
          message: "Missing structural input",
          payload: { section: "foundation" },
          created_at: "2024-01-01T09:05:00Z",
        },
      ],
      exports: [
        {
          export_id: "export-1",
          session_id: "report-17",
          status: "pending",
          format: "pdf",
          output_path: "/private/tmp/report.pdf",
          diagnostics: { token: "sk-redacted" },
          created_at: "2024-01-01T09:06:00Z",
          completed_at: null,
        },
      ],
    } as never);

    render(<ReportView />);

    expect(screen.getByTestId("report-view")).toBeInTheDocument();
    expect(screen.getByTestId("report-status-badge")).toHaveTextContent("blocked");
    expect(screen.getByTestId("report-current-stage")).toHaveTextContent("Inventory");

    const activeStage = screen.getByTestId("report-stage-stage-inventory");
    expect(activeStage).toHaveAttribute("data-current", "true");
    expect(activeStage).toHaveClass("bg-brand-blue-soft");

    const completeStage = screen.getByTestId("report-stage-stage-review");
    expect(completeStage).toHaveAttribute("data-current", "false");
    expect(completeStage).toHaveClass("bg-white");
    expect(completeStage).toHaveClass("border-brand-line");

    expect(screen.getByTestId("current-gate-banner")).toHaveTextContent(
      "Answer the open gate in chat to continue",
    );

    expect(screen.getByTestId("report-artifact-artifact-plan")).toHaveTextContent(
      "Foundation survey",
    );
    expect(screen.queryByText("Ignore me")).not.toBeInTheDocument();

    expect(screen.getByTestId("validation-group-warning")).toBeInTheDocument();
    expect(screen.getByTestId("validation-group-blocker")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("Missing structural input")).toBeInTheDocument();
    expect(screen.getByText("W001")).toBeInTheDocument();
    expect(screen.getByText("B007")).toBeInTheDocument();

    const pendingExport = screen.getByTestId("report-export-export-1");
    expect(pendingExport).toHaveTextContent("pdf");
    expect(pendingExport).toHaveTextContent("pending");
    expect(pendingExport).toHaveTextContent(/report\.pdf/);
    expect(within(pendingExport).queryByRole("link", { name: /download pdf/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/\/private\/tmp\/report\.pdf/)).not.toBeInTheDocument();
  });

  it("renders a ready PDF download link with basename-only text and encoded ids", () => {
    useChatStore.setState({
      activeReportId: "report 17/unsafe",
      activeView: "report",
      reportStatus: "complete",
      exports: [
        {
          export_id: "export 1/final",
          session_id: "report 17/unsafe",
          status: "ready",
          format: "PDF",
          output_path: "C:\\private\\reports\\report-final.pdf",
          diagnostics: { pages: 4 },
          created_at: "2024-01-01T09:06:00Z",
          completed_at: "2024-01-01T09:07:00Z",
        },
      ],
    } as never);

    render(<ReportView />);

    const exportCard = screen.getByTestId("report-export-export 1/final");
    expect(exportCard).toHaveTextContent("Output path: report-final.pdf");
    expect(screen.queryByText(/C:\\private\\reports\\report-final\.pdf/)).not.toBeInTheDocument();

    const link = within(exportCard).getByRole("link", {
      name: "Download PDF report-final.pdf",
    });
    expect(link).toHaveTextContent("Download PDF");
    expect(link).toHaveAttribute(
      "href",
      "http://localhost:8000/api/reports/report%2017%2Funsafe/exports/export%201%2Ffinal/download",
    );
    expect(link.getAttribute("href")).not.toContain("report-final.pdf");
    expect(link.getAttribute("href")).not.toContain("private");
  });

  it("suppresses download links for unavailable exports", () => {
    useChatStore.setState({
      activeReportId: "report-17",
      activeView: "report",
      reportStatus: "complete",
      exports: [
        {
          export_id: "export-pending",
          session_id: "report-17",
          status: "pending",
          format: "pdf",
          output_path: "/private/tmp/pending.pdf",
          diagnostics: {},
          created_at: "2024-01-01T09:06:00Z",
          completed_at: null,
        },
        {
          export_id: "export-failed",
          session_id: "report-17",
          status: "failed",
          format: "pdf",
          output_path: "/private/tmp/failed.pdf",
          diagnostics: { error: "synthetic failure" },
          created_at: "2024-01-01T09:06:00Z",
          completed_at: null,
        },
        {
          export_id: "export-docx",
          session_id: "report-17",
          status: "ready",
          format: "docx",
          output_path: "/private/tmp/report.docx",
          diagnostics: {},
          created_at: "2024-01-01T09:06:00Z",
          completed_at: "2024-01-01T09:07:00Z",
        },
        {
          export_id: "export-no-path",
          session_id: "report-17",
          status: "ready",
          format: "pdf",
          output_path: null,
          diagnostics: {},
          created_at: "2024-01-01T09:06:00Z",
          completed_at: "2024-01-01T09:07:00Z",
        },
      ],
    } as never);

    render(<ReportView />);

    expect(screen.queryAllByRole("link", { name: /download pdf/i })).toHaveLength(0);
    expect(screen.getByTestId("report-export-export-pending")).toHaveTextContent("pending");
    expect(screen.getByTestId("report-export-export-failed")).toHaveTextContent("failed");
    expect(screen.getByTestId("report-export-export-docx")).toHaveTextContent("docx");
    expect(screen.getByTestId("report-export-export-no-path")).toHaveTextContent(
      "Output path: pending",
    );
    expect(screen.queryByText(/\/private\/tmp\//)).not.toBeInTheDocument();
  });

  it("suppresses ready PDF download links when there is no active report id", () => {
    useChatStore.setState({
      activeReportId: null,
      activeView: "report",
      reportStatus: "complete",
      exports: [
        {
          export_id: "export-ready",
          session_id: "report-17",
          status: "ready",
          format: "pdf",
          output_path: "/private/tmp/report-ready.pdf",
          diagnostics: {},
          created_at: "2024-01-01T09:06:00Z",
          completed_at: "2024-01-01T09:07:00Z",
        },
      ],
    } as never);

    render(<ReportView />);

    const exportCard = screen.getByTestId("report-export-export-ready");
    expect(exportCard).toHaveTextContent("Output path: report-ready.pdf");
    expect(within(exportCard).queryByRole("link", { name: /download pdf/i })).not.toBeInTheDocument();
  });

  it("renders empty-state hints when report data has not arrived yet", () => {
    render(<ReportView />);

    expect(screen.getByTestId("report-view")).toBeInTheDocument();
    expect(screen.getByTestId("report-current-stage")).toHaveTextContent(
      "Waiting for the first stage to start",
    );
    expect(
      screen.getByText("Waiting for the first stage to start", { selector: "p" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Section plan will appear once the inventory stage completes"),
    ).toBeInTheDocument();
    expect(screen.getByText("No validation findings yet")).toBeInTheDocument();
    expect(screen.getByText("No exports yet")).toBeInTheDocument();
  });
});
