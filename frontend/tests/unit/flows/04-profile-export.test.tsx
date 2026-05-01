import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import HomePage from "@/app/page";
import { useChatStore } from "@/lib/store";

describe("Top-right profile button + export PDF", () => {
  it("opens ProfilePanel and shows the export button", async () => {
    useChatStore.getState().advanceOnboarding("ready");
    render(<HomePage />);
    const user = userEvent.setup();

    expect(screen.queryByTestId("profile-panel")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("button-profile"));

    expect(screen.getByTestId("profile-panel")).toBeInTheDocument();
    const exportBtn = screen.getByRole("button", {
      name: /bob-report|export.*pdf/i,
    });
    expect(exportBtn).toBeInTheDocument();
    await user.click(exportBtn);
  });
});
