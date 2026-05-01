import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SettingsModal } from "@/components/settings/SettingsModal";
import { useChatStore } from "@/lib/store";

describe("Settings · bob-regulations + bob-template tabs", () => {
  it("shows both tabs and a list of bob-regulations", async () => {
    useChatStore.getState().setSettingsOpen(true);
    render(<SettingsModal />);

    expect(
      screen.getByRole("tab", { name: /bob-regulations|guidelines|richtlinien/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /bob-template|template|vorlage/i }),
    ).toBeInTheDocument();

    expect(screen.getByText(/bob-regulation 001/i)).toBeInTheDocument();
  });

  it("editing a side-comment in template marks the section as AI-rewritten", async () => {
    useChatStore.getState().setSettingsOpen(true);
    useChatStore.getState().setSettingsTab("template");
    render(<SettingsModal />);
    const user = userEvent.setup();

    const formulaInput = screen.getByDisplayValue(
      /bob-use-load = 3 bob-units/i,
    ) as HTMLInputElement | HTMLTextAreaElement;
    await user.clear(formulaInput);
    await user.type(formulaInput, "bob-use-load = 5 bob-units");

    expect(
      screen.getByTestId("rewritten-indicator-tpl_loads"),
    ).toBeInTheDocument();
  });
});
