import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import HomePage from "@/app/page";
import { useChatStore } from "@/lib/store";

describe("Drop file → snapshot + warnings + highlight", () => {
  it("dropping a file creates a snapshot, adds red+yellow nodes, and highlights warning lines in preview", async () => {
    useChatStore.getState().advanceOnboarding("ready");
    render(<HomePage />);
    const user = userEvent.setup();

    const initialSnaps = useChatStore.getState().snapshots.length;

    const dropInput = screen.getByTestId(
      "input-drop-file",
    ) as HTMLInputElement;
    const file = new File(["pdf"], "Bodengutachten.pdf", {
      type: "application/pdf",
    });
    await user.upload(dropInput, file);

    expect(useChatStore.getState().snapshots.length).toBe(initialSnaps + 1);

    const warnings = useChatStore.getState().warnings;
    expect(warnings.some((w) => w.severity === "critical")).toBe(true);
    expect(warnings.some((w) => w.severity === "impacted")).toBe(true);

    expect(
      screen.getAllByTestId(/node-warning-critical/).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByTestId(/node-warning-impacted/).length,
    ).toBeGreaterThan(0);

    // Open the dropped file in the preview and confirm the warning range is highlighted.
    const droppedFile = useChatStore
      .getState()
      .files.find((f) => f.name === "Bodengutachten.pdf");
    expect(droppedFile).toBeDefined();
    useChatStore.getState().setActiveFile(droppedFile!.id);

    const warnLines = await screen.findAllByTestId("preview-warning-line");
    expect(warnLines.length).toBeGreaterThan(0);
  });
});
