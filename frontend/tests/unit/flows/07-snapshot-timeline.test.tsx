import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import HomePage from "@/app/page";
import { useChatStore } from "@/lib/store";

describe("Snapshot timeline (bottom dock)", () => {
  it("clicking an older snapshot updates graph + warnings list to that frozen state", async () => {
    useChatStore.getState().advanceOnboarding("ready");
    render(<HomePage />);
    const user = userEvent.setup();

    // Drop a file to create a 2nd snapshot with warnings.
    const dropInput = screen.getByTestId("input-drop-file") as HTMLInputElement;
    const file = new File(["pdf"], "Bodengutachten.pdf", {
      type: "application/pdf",
    });
    await user.upload(dropInput, file);

    const snapshots = useChatStore.getState().snapshots;
    expect(snapshots.length).toBeGreaterThanOrEqual(2);

    // After drop we should have warnings.
    expect(useChatStore.getState().warnings.length).toBeGreaterThan(0);

    // Click the initial snapshot in the dock — should reset warnings to [].
    const initial = snapshots[0];
    await user.click(screen.getByTestId(`snapshot-${initial.id}`));

    expect(useChatStore.getState().activeSnapshotId).toBe(initial.id);
    expect(useChatStore.getState().warnings).toEqual([]);
    expect(screen.getByTestId("warnings-empty")).toBeInTheDocument();
  });
});
