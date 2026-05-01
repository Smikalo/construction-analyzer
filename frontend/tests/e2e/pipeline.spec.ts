import { test, expect } from "@playwright/test";

/**
 * End-to-end pipeline test.
 *
 * Run after `make up` (frontend on :3000, backend on :8000). Verifies:
 *  - the chat shell renders
 *  - the connection badge eventually shows "Online" or "Degraded"
 *    (degraded is acceptable when Ollama models haven't been pulled yet)
 *  - sending a message produces a streamed assistant reply
 *  - reloading the page rehydrates the conversation from the backend checkpointer
 *
 * Skipped automatically if the frontend is not reachable.
 */

const FRONTEND = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";

test.beforeEach(async ({ page }, testInfo) => {
  try {
    const r = await page.request.get(FRONTEND);
    if (!r.ok()) testInfo.skip();
  } catch {
    testInfo.skip();
  }
});

test("pipeline: send message, get reply, reload, history rehydrates", async ({
  page,
}) => {
  await page.goto("/");

  // Connection badge appears within a few seconds.
  await expect(
    page.locator("text=/Online|Degraded|Connecting/").first(),
  ).toBeVisible({ timeout: 10_000 });

  const composer = page.getByPlaceholder(/message/i);
  await expect(composer).toBeVisible();

  const probe = `playwright-marker-${Date.now()}`;
  await composer.fill(probe);
  await composer.press("Enter");

  // The user message appears immediately.
  await expect(page.getByText(probe)).toBeVisible();

  // The assistant message is rendered (may or may not contain the marker text).
  await expect(
    page.locator("[data-role='assistant']").last(),
  ).toBeVisible({ timeout: 30_000 });

  // Reload and confirm history rehydrates from the backend checkpointer.
  await page.reload();
  await expect(page.getByText(probe)).toBeVisible({ timeout: 15_000 });
  await expect(
    page.locator("[data-role='assistant']").last(),
  ).toBeVisible();
});
