import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import HomePage from "@/app/page";
import { useChatStore } from "@/lib/store";

describe("Chat citations → graph highlights", () => {
  it("sending a chat message highlights cited nodes and the connecting edges", async () => {
    useChatStore.getState().advanceOnboarding("ready");
    render(<HomePage />);
    const user = userEvent.setup();

    const composer = screen.getByPlaceholderText(/message|frage|frag|bob/i);
    await user.type(
      composer,
      "Which bob-files relate to the bob-foundation?{enter}",
    );

    const highlights = useChatStore.getState().chatHighlights;
    expect(highlights.nodeIds).toEqual(
      expect.arrayContaining(["n_foundation", "n_floorplan", "n_blueprint"]),
    );
    expect(highlights.edgeIds.length).toBeGreaterThan(0);

    expect(
      screen.getAllByTestId(/node-highlight-n_/).length,
    ).toBeGreaterThanOrEqual(3);
  });
});
