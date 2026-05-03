"use client";

import { useMemo } from "react";
import { motion } from "framer-motion";
import { reportExportDownloadUrl } from "@/lib/api";
import { useChatStore } from "@/lib/store";
import type {
  ReportArtifact,
  ReportExport,
  ReportSessionStatus,
  ReportStage,
  ReportValidationFinding,
  ReportValidationSeverity,
} from "@/types";

const STATUS_BADGE_CLASSES: Record<ReportSessionStatus, string> = {
  pending: "border-brand-line bg-brand-surface-soft text-brand-subtle",
  active: "border-brand-blue bg-brand-blue-soft text-brand-blue",
  blocked: "border-brand-orange bg-brand-orange-soft text-brand-orange",
  complete: "border-emerald-200 bg-emerald-50 text-emerald-700",
  failed: "border-red-200 bg-red-50 text-red-700",
};

const STAGE_ROW_CLASSES: Record<ReportStage["status"], string> = {
  pending: "border-brand-line bg-brand-surface-soft",
  active: "border-brand-blue bg-brand-blue-soft",
  complete: "border-brand-line bg-white",
  failed: "border-red-200 bg-red-50",
};

const FINDING_SEVERITY_LABELS: Record<ReportValidationSeverity, string> = {
  info: "Info",
  warning: "Warnings",
  blocker: "Blockers",
};

function readText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return `${date.toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

function stageCardClassName(stage: ReportStage, isCurrent: boolean): string {
  return [
    "rounded-2xl border px-3 py-3 shadow-sm transition",
    STAGE_ROW_CLASSES[stage.status],
    isCurrent ? "ring-1 ring-brand-blue/30" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function badgeClassName(status: ReportSessionStatus | ReportStage["status"]): string {
  return [
    "inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.16em]",
    STATUS_BADGE_CLASSES[status as ReportSessionStatus] ?? STATUS_BADGE_CLASSES.pending,
  ].join(" ");
}

function summarizeOutputPath(path: string | null): string | null {
  if (!path) return null;
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function artifactLabel(artifact: ReportArtifact): string {
  return readText(artifact.content.title) ?? artifact.kind;
}

function pickCurrentStage(stages: ReportStage[]): ReportStage | null {
  const active = stages.find((stage) => stage.status === "active");
  if (active) return active;

  const failed = stages.find((stage) => stage.status === "failed");
  if (failed) return failed;

  return stages[stages.length - 1] ?? null;
}

function groupFindings(findings: ReportValidationFinding[]) {
  return findings.reduce(
    (acc, finding) => {
      acc[finding.severity].push(finding);
      return acc;
    },
    {
      info: [] as ReportValidationFinding[],
      warning: [] as ReportValidationFinding[],
      blocker: [] as ReportValidationFinding[],
    },
  );
}

export function ReportView() {
  const activeReportId = useChatStore((s) => s.activeReportId);
  const reportStatus = useChatStore((s) => s.reportStatus);
  const reportError = useChatStore((s) => s.reportError);
  const stages = useChatStore((s) => s.stages);
  const currentGate = useChatStore((s) => s.currentGate);
  const artifacts = useChatStore((s) => s.artifacts);
  const validationFindings = useChatStore((s) => s.validationFindings);
  const exports = useChatStore((s) => s.exports);
  const reportCards = useChatStore((s) => s.reportCards);

  const currentStage = useMemo(() => pickCurrentStage(stages), [stages]);
  const latestReportCardStageName =
    reportCards.length > 0 ? readText(reportCards[reportCards.length - 1]?.stage_name) : null;
  const currentStageLabel =
    currentStage?.name ?? latestReportCardStageName ?? "Waiting for the first stage to start";

  const sectionArtifacts = useMemo(
    () =>
      artifacts.filter(
        (artifact) => artifact.kind === "section_plan" || artifact.kind === "section_draft",
      ),
    [artifacts],
  );
  const groupedFindings = useMemo(() => groupFindings(validationFindings), [validationFindings]);
  const status = reportStatus ?? "pending";
  const hasCurrentGateBanner = Boolean(currentGate || status === "blocked");

  return (
    <motion.div
      data-testid="report-view"
      aria-label="Report workspace"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto border-b border-brand-line bg-brand-surface-soft"
    >
      <div className="space-y-3 p-3">
        <section className="rounded-2xl border border-brand-line bg-white p-3 shadow-sm">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-brand-subtle">
                Report session
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <h1 className="truncate text-[14px] font-semibold text-brand-ink">
                  {activeReportId ?? "No active report session"}
                </h1>
                <span
                  data-testid="report-status-badge"
                  className={badgeClassName(status)}
                >
                  {status}
                </span>
              </div>
              <div className="mt-2 text-[12px] text-brand-subtle">
                Current stage{" "}
                <span data-testid="report-current-stage" className="font-medium text-brand-ink">
                  {currentStageLabel}
                </span>
              </div>
            </div>

            {reportError ? (
              <p
                data-testid="report-error"
                role="alert"
                className="max-w-[24rem] rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[12px] leading-relaxed text-red-700"
              >
                Latest error: {reportError}
              </p>
            ) : null}
          </div>
        </section>

        <section className="rounded-2xl border border-brand-line bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[12px] font-semibold text-brand-blue">Stages timeline</h2>
            <span className="rounded-full bg-brand-surface-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
              {stages.length} bob-stages
            </span>
          </div>

          {stages.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-brand-line bg-brand-surface-soft px-3 py-3 text-[12px] text-brand-subtle">
              Waiting for the first stage to start
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {stages.map((stage) => {
                const isCurrent = currentStage?.stage_id === stage.stage_id;
                return (
                  <li key={stage.stage_id}>
                    <article
                      data-testid={`report-stage-${stage.stage_id}`}
                      data-current={isCurrent ? "true" : "false"}
                      data-status={stage.status}
                      className={stageCardClassName(stage, isCurrent)}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-brand-subtle">
                            {stage.stage_id}
                          </div>
                          <div className="mt-1 text-[12.5px] font-semibold text-brand-ink">
                            {stage.name}
                          </div>
                        </div>
                        <span className={badgeClassName(stage.status)}>{stage.status}</span>
                      </div>

                      <dl className="mt-2 grid gap-2 text-[11px] text-brand-subtle sm:grid-cols-2">
                        <div>
                          <dt className="font-medium text-brand-ink">Started</dt>
                          <dd>{formatTimestamp(stage.started_at)}</dd>
                        </div>
                        <div>
                          <dt className="font-medium text-brand-ink">Completed</dt>
                          <dd>{formatTimestamp(stage.completed_at)}</dd>
                        </div>
                      </dl>
                    </article>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {hasCurrentGateBanner ? (
          <section
            data-testid="current-gate-banner"
            className={[
              "rounded-2xl border px-3 py-3 shadow-sm",
              currentGate
                ? "border-brand-blue bg-brand-blue-soft"
                : "border-brand-line bg-brand-surface-soft",
            ].join(" ")}
          >
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-brand-subtle">
              Current gate
            </div>
            <div className="mt-1 text-[12.5px] font-semibold text-brand-ink">
              {currentGate
                ? "Answer the open gate in chat to continue"
                : "Waiting for user input"}
            </div>
            {currentGate ? (
              <div className="mt-1 text-[11px] text-brand-subtle">
                Gate {currentGate.gate_id} is open in the chat panel.
              </div>
            ) : null}
          </section>
        ) : null}

        <section className="rounded-2xl border border-brand-line bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[12px] font-semibold text-brand-blue">Section progress</h2>
            <span className="rounded-full bg-brand-surface-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
              {sectionArtifacts.length} tracked sections
            </span>
          </div>

          {sectionArtifacts.length === 0 ? (
            <p className="mt-3 rounded-xl border border-dashed border-brand-line bg-brand-surface-soft px-3 py-3 text-[12px] text-brand-subtle">
              Section plan will appear once the inventory stage completes
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {sectionArtifacts.map((artifact) => (
                <li key={artifact.artifact_id}>
                  <article
                    data-testid={`report-artifact-${artifact.artifact_id}`}
                    className="flex items-start gap-3 rounded-2xl border border-brand-line bg-brand-surface-soft px-3 py-3 shadow-sm"
                  >
                    <span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.12em] text-brand-subtle">
                      {artifact.kind}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[10.5px] font-semibold uppercase tracking-[0.18em] text-brand-subtle">
                        {artifact.artifact_id}
                      </div>
                      <div className="mt-1 text-[12.5px] font-semibold text-brand-ink">
                        {artifactLabel(artifact)}
                      </div>
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-brand-line bg-white p-3 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[12px] font-semibold text-brand-blue">Validation & export</h2>
            <span className="rounded-full bg-brand-surface-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
              {validationFindings.length} findings · {exports.length} exports
            </span>
          </div>

          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            <section className="rounded-2xl border border-brand-line bg-brand-surface-soft p-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-[12px] font-semibold text-brand-ink">Validation findings</h3>
                <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
                  grouped by severity
                </span>
              </div>

              {validationFindings.length === 0 ? (
                <p className="mt-3 rounded-xl border border-dashed border-brand-line bg-white px-3 py-3 text-[12px] text-brand-subtle">
                  No validation findings yet
                </p>
              ) : (
                <div className="mt-3 space-y-3">
                  {(Object.keys(groupedFindings) as ReportValidationSeverity[]).map((severity) => {
                    const findings = groupedFindings[severity];
                    if (findings.length === 0) return null;

                    return (
                      <section key={severity} data-testid={`validation-group-${severity}`}>
                        <div className="flex items-center gap-2">
                          <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-medium uppercase tracking-[0.12em] text-brand-subtle">
                            {severity}
                          </span>
                          <h4 className="text-[11.5px] font-semibold text-brand-ink">
                            {FINDING_SEVERITY_LABELS[severity]}
                          </h4>
                        </div>
                        <ul className="mt-2 space-y-2">
                          {findings.map((finding) => (
                            <li
                              key={finding.finding_id}
                              data-testid={`validation-finding-${finding.finding_id}`}
                              className="rounded-xl border border-brand-line bg-white px-3 py-2"
                            >
                              <div className="flex items-start justify-between gap-3">
                                <p className="min-w-0 text-[12px] leading-relaxed text-brand-ink">
                                  {finding.message}
                                </p>
                                <span className="shrink-0 rounded-md bg-brand-surface-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
                                  {finding.code ?? "—"}
                                </span>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </section>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="rounded-2xl border border-brand-line bg-brand-surface-soft p-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-[12px] font-semibold text-brand-ink">Exports</h3>
                <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-medium text-brand-subtle">
                  delivery state
                </span>
              </div>

              {exports.length === 0 ? (
                <p className="mt-3 rounded-xl border border-dashed border-brand-line bg-white px-3 py-3 text-[12px] text-brand-subtle">
                  No exports yet
                </p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {exports.map((reportExport: ReportExport) => {
                    const outputPath = summarizeOutputPath(reportExport.output_path);
                    const canDownloadPdf = Boolean(
                      activeReportId &&
                        outputPath &&
                        reportExport.status === "ready" &&
                        reportExport.format.toLowerCase() === "pdf",
                    );
                    const downloadLabel = outputPath
                      ? `Download PDF ${outputPath}`
                      : `Download PDF ${reportExport.export_id}`;

                    return (
                      <li
                        key={reportExport.export_id}
                        data-testid={`report-export-${reportExport.export_id}`}
                        className="rounded-xl border border-brand-line bg-white px-3 py-2 shadow-sm"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-[12px] font-semibold text-brand-ink">
                              {reportExport.format}
                            </div>
                            <div className="mt-1 text-[11px] text-brand-subtle">
                              {outputPath ? `Output path: ${outputPath}` : "Output path: pending"}
                            </div>
                            {canDownloadPdf && activeReportId ? (
                              <a
                                href={reportExportDownloadUrl(
                                  activeReportId,
                                  reportExport.export_id,
                                )}
                                aria-label={downloadLabel}
                                className="mt-2 inline-flex min-h-9 items-center rounded-full border border-brand-blue bg-brand-blue-soft px-3 text-[11.5px] font-medium text-brand-blue transition-colors hover:bg-white focus:outline-none focus:ring-2 focus:ring-brand-blue focus:ring-offset-2"
                              >
                                Download PDF
                              </a>
                            ) : null}
                          </div>
                          <span className={badgeClassName(reportExport.status === "ready" ? "complete" : reportExport.status === "failed" ? "failed" : "pending")}>{reportExport.status}</span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>
        </section>
      </div>
    </motion.div>
  );
}
