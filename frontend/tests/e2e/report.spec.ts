import { expect, type Page, type Route, test } from "@playwright/test";

const FRONTEND = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const BACKEND = "http://localhost:8000";
const SESSION_ID = "report-123";
const EXPORT_ID = "export-pdf";
const OUTPUT_BASENAME = "synthetic-report.pdf";

async function fulfillJson(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function sseMessage(payload: unknown): string {
  return `event: message\ndata: ${JSON.stringify(payload)}\n\n`;
}

function openGateInspection() {
  return {
    session: {
      session_id: SESSION_ID,
      status: "blocked",
      current_stage: "bootstrap",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:01Z",
      last_error: null,
      metadata: { source: "playwright" },
    },
    current_stage: "bootstrap",
    stages: [
      {
        stage_id: "stage-bootstrap",
        session_id: SESSION_ID,
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
        session_id: SESSION_ID,
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
        session_id: SESSION_ID,
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
      session_id: SESSION_ID,
      status: "complete",
      current_stage: "export_report",
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:09Z",
      last_error: null,
      metadata: { source: "playwright" },
    },
    current_stage: "export_report",
    stages: [
      {
        stage_id: "stage-bootstrap",
        session_id: SESSION_ID,
        name: "bootstrap",
        status: "complete",
        started_at: "2024-01-01T00:00:00Z",
        completed_at: "2024-01-01T00:00:02Z",
        summary: "Template accepted",
        error: null,
      },
      {
        stage_id: "stage-inventory",
        session_id: SESSION_ID,
        name: "inventory",
        status: "complete",
        started_at: "2024-01-01T00:00:02Z",
        completed_at: "2024-01-01T00:00:04Z",
        summary: "Synthetic evidence inventory complete",
        error: null,
      },
      {
        stage_id: "stage-validation",
        session_id: SESSION_ID,
        name: "validate_report",
        status: "complete",
        started_at: "2024-01-01T00:00:04Z",
        completed_at: "2024-01-01T00:00:06Z",
        summary: "Validation complete with warnings",
        error: null,
      },
      {
        stage_id: "stage-export",
        session_id: SESSION_ID,
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
        session_id: SESSION_ID,
        stage_id: "stage-inventory",
        kind: "section_plan",
        content: { title: "Synthetic report structure" },
        created_at: "2024-01-01T00:00:04Z",
      },
      {
        artifact_id: "section-draft",
        session_id: SESSION_ID,
        stage_id: "stage-validation",
        kind: "section_draft",
        content: { title: "Validated synthetic draft" },
        created_at: "2024-01-01T00:00:06Z",
      },
    ],
    validation_findings: [
      {
        finding_id: "finding-warning",
        session_id: SESSION_ID,
        severity: "warning",
        code: "SYN-WARN",
        message: "Synthetic evidence should be reviewed before signing.",
        payload: { section: "Evidence" },
        created_at: "2024-01-01T00:00:06Z",
      },
      {
        finding_id: "finding-info",
        session_id: SESSION_ID,
        severity: "info",
        code: "SYN-INFO",
        message: "Synthetic export diagnostics are available.",
        payload: { pages: 6 },
        created_at: "2024-01-01T00:00:07Z",
      },
    ],
    exports: [
      {
        export_id: EXPORT_ID,
        session_id: SESSION_ID,
        status: "ready",
        format: "pdf",
        output_path: `/private/reports/${OUTPUT_BASENAME}`,
        diagnostics: { pages: 6 },
        created_at: "2024-01-01T00:00:07Z",
        completed_at: "2024-01-01T00:00:09Z",
      },
    ],
    recent_logs: [
      {
        log_id: "log-bootstrap-started",
        session_id: SESSION_ID,
        stage_id: "stage-bootstrap",
        level: "info",
        message: "Report bootstrap stage started",
        payload: { stage_name: "bootstrap" },
        created_at: "2024-01-01T00:00:00Z",
      },
      {
        log_id: "log-validation-complete",
        session_id: SESSION_ID,
        stage_id: "stage-validation",
        level: "info",
        message: "Report validate_report stage completed",
        payload: { stage_name: "validate_report", findings: 2 },
        created_at: "2024-01-01T00:00:06Z",
      },
      {
        log_id: "log-export-complete",
        session_id: SESSION_ID,
        stage_id: "stage-export",
        level: "info",
        message: "Report export_report stage completed",
        payload: { stage_name: "export_report", exports: 1 },
        created_at: "2024-01-01T00:00:09Z",
      },
    ],
  };
}

async function mockReportBackend(page: Page): Promise<void> {
  let gateAnswered = false;

  await page.route("**/health", async (route) => {
    await fulfillJson(route, { status: "ok" });
  });

  await page.route("**/ready", async (route) => {
    await fulfillJson(route, {
      status: "ready",
      ollama: true,
      postgres: true,
      checkpointer: true,
      kb: true,
      detail: null,
    });
  });

  await page.route("**/api/reports", async (route) => {
    const request = route.request();
    if (request.method() !== "POST") {
      await fulfillJson(route, { error: "unexpected method" }, 405);
      return;
    }

    expect(await request.postDataJSON()).toEqual({});
    await fulfillJson(
      route,
      {
        session_id: SESSION_ID,
        status: "blocked",
        current_stage: "bootstrap",
        resumed: false,
      },
      201,
    );
  });

  await page.route("**/api/reports/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;

    if (request.method() === "GET" && pathname === `/api/reports/${SESSION_ID}`) {
      await fulfillJson(route, gateAnswered ? completedInspection() : openGateInspection());
      return;
    }

    if (
      request.method() === "GET" &&
      pathname === `/api/reports/${SESSION_ID}/stream`
    ) {
      const stageStarted = {
        session_id: SESSION_ID,
        stage_id: "stage-bootstrap",
        stage_name: "bootstrap",
        kind: "stage_started",
        message: "Bootstrap stage started",
        created_at: "2024-01-01T00:00:00Z",
        payload: { stage_name: "bootstrap" },
      };
      const gateOpened = {
        session_id: SESSION_ID,
        stage_id: "stage-bootstrap",
        stage_name: "bootstrap",
        kind: "gate_opened",
        message: "Template confirmation gate opened",
        created_at: "2024-01-01T00:00:01Z",
        payload: { gate_id: "template_confirmation" },
      };
      const gate = openGateInspection().gates[0];
      const body =
        sseMessage({ type: "report_card", data: stageStarted.message, payload: stageStarted }) +
        sseMessage({ type: "report_card", data: gateOpened.message, payload: gateOpened }) +
        sseMessage({ type: "report_gate", data: gate.question.label, payload: gate }) +
        sseMessage({ type: "done", data: "" });

      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body,
      });
      return;
    }

    if (
      request.method() === "POST" &&
      pathname === `/api/reports/${SESSION_ID}/gates/template_confirmation/answer`
    ) {
      expect(await request.postDataJSON()).toEqual({
        answer: {
          question_id: "template_confirmation",
          value: "general_project_dossier",
        },
      });
      gateAnswered = true;
      await route.fulfill({ status: 204, body: "" });
      return;
    }

    if (
      request.method() === "GET" &&
      pathname === `/api/reports/${SESSION_ID}/exports/${EXPORT_ID}/download`
    ) {
      await route.fulfill({
        status: 200,
        contentType: "application/pdf",
        headers: {
          "content-disposition": `attachment; filename="${OUTPUT_BASENAME}"`,
        },
        body: "%PDF-1.4\n% synthetic report\n",
      });
      return;
    }

    await fulfillJson(route, { error: "unmocked report route", pathname }, 404);
  });
}

async function completeOnboarding(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("input-project-zip").setInputFiles({
    name: "synthetic-project.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("synthetic project zip"),
  });
  await page.getByPlaceholder("bob-email + Enter").fill("qa@example.test");
  await page.getByPlaceholder("bob-email + Enter").press("Enter");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByTestId("graph-view")).toBeVisible({ timeout: 5_000 });
}

test.beforeEach(async ({ page }, testInfo) => {
  try {
    const response = await page.request.get(FRONTEND, { timeout: 5_000 });
    if (!response.ok()) testInfo.skip();
  } catch {
    testInfo.skip();
  }
});

test("report flow: Build Report gate reaches ready PDF download", async ({ page }) => {
  await mockReportBackend(page);
  await completeOnboarding(page);

  await page.getByRole("button", { name: /build report/i }).click();

  await expect(page.getByTestId("report-view")).toBeVisible();
  await expect(
    page.getByRole("article", { name: /stage started report card/i }),
  ).toBeVisible();
  await expect(page.getByText("Bootstrap stage started")).toBeVisible();

  const gateGroup = page.getByRole("group", {
    name: "Confirm the report template for this session.",
  });
  await expect(gateGroup).toBeVisible();
  await expect(page.getByTestId("current-gate-banner")).toContainText(
    "Answer the open gate in chat to continue",
  );

  await page.getByLabel("General project dossier").check();
  await page.getByRole("button", { name: /submit/i }).click();

  await expect(gateGroup).toHaveCount(0);
  await expect(page.getByTestId("report-status-badge")).toContainText("complete");
  await expect(page.getByTestId("report-current-stage")).toContainText("export_report");
  await expect(page.getByTestId("report-stage-stage-export")).toHaveAttribute(
    "data-status",
    "complete",
  );
  await expect(page.getByTestId("report-artifact-section-plan")).toContainText(
    "Synthetic report structure",
  );
  await expect(page.getByTestId("validation-group-warning")).toContainText(
    "Synthetic evidence should be reviewed before signing.",
  );

  const exportCard = page.getByTestId(`report-export-${EXPORT_ID}`);
  await expect(exportCard).toContainText("ready");
  await expect(exportCard).toContainText(`Output path: ${OUTPUT_BASENAME}`);
  await expect(page.getByText(/\/reports\/synthetic-report\.pdf/)).toHaveCount(0);

  const downloadLink = page.getByRole("link", {
    name: `Download PDF ${OUTPUT_BASENAME}`,
  });
  await expect(downloadLink).toHaveAttribute(
    "href",
    `${BACKEND}/api/reports/${SESSION_ID}/exports/${EXPORT_ID}/download`,
  );

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadLink.click(),
  ]);
  expect(download.suggestedFilename()).toBe(OUTPUT_BASENAME);
});
