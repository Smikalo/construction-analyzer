import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { useChatStore } from "@/lib/store";

function uploadZip(input: HTMLElement, name: string) {
  const file = new File(["zip-bytes"], name, { type: "application/zip" });
  return userEvent.upload(input, file);
}

describe("Onboarding · Step 1 · project zip", () => {
  it("renders the zip dropzone and a hint about uploading the project", () => {
    render(<OnboardingWizard />);
    expect(screen.getByTestId("dropzone-project-zip")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /projekt|project/i }),
    ).toBeInTheDocument();
  });

  it("advances to step 2 once a zip is uploaded", async () => {
    render(<OnboardingWizard />);
    const input = screen.getByTestId(
      "input-project-zip",
    ) as HTMLInputElement;
    await uploadZip(input, "B04.zip");

    expect(useChatStore.getState().projectZipName).toBe("B04.zip");
    expect(useChatStore.getState().onboardingStep).toBe("step2");
  });
});
