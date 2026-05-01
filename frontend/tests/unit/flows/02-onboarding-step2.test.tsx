import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { useChatStore } from "@/lib/store";

describe("Onboarding · Step 2 · team emails + previous conversations", () => {
  it("collects emails as chips, accepts conversations zip, shows bot-CC helper text, advances", async () => {
    useChatStore.getState().advanceOnboarding("step2");
    render(<OnboardingWizard />);
    const user = userEvent.setup();

    expect(
      screen.getAllByText(/bot.*cc|cc.*bot|email.*domain/i).length,
    ).toBeGreaterThan(0);

    const emailInput = screen.getByPlaceholderText(/e-?mail/i);
    await user.type(emailInput, "lena.schulz@bob-the-builder.de{enter}");
    await user.type(emailInput, "tobias.weber@bob-the-builder.de{enter}");

    expect(screen.getByText("lena.schulz@bob-the-builder.de")).toBeInTheDocument();
    expect(screen.getByText("tobias.weber@bob-the-builder.de")).toBeInTheDocument();

    const convosInput = screen.getByTestId(
      "input-conversations-zip",
    ) as HTMLInputElement;
    const file = new File(["zip-bytes"], "msgs.zip", {
      type: "application/zip",
    });
    await user.upload(convosInput, file);

    expect(useChatStore.getState().conversationsZipName).toBe("msgs.zip");
    expect(useChatStore.getState().projectEmails).toEqual([
      "lena.schulz@bob-the-builder.de",
      "tobias.weber@bob-the-builder.de",
    ]);

    await user.click(screen.getByRole("button", { name: /weiter|continue/i }));

    expect(useChatStore.getState().onboardingStep).toBe("step3");
  });
});
