import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import HomePage from "@/app/page";
import { useChatStore } from "@/lib/store";

describe("Onboarding · Step 3 · memory-palace loading and transition", () => {
  it("renders loading screen when onboardingStep === 'step3'", () => {
    useChatStore.getState().advanceOnboarding("step3");
    render(<HomePage />);
    expect(screen.getByTestId("loading-memory-palace")).toBeInTheDocument();
  });

  it("renders the AppShell with file tree, graph, preview, and chat once 'ready'", () => {
    useChatStore.getState().advanceOnboarding("ready");
    render(<HomePage />);
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("file-tree")).toBeInTheDocument();
    expect(screen.getByTestId("graph-view")).toBeInTheDocument();
    expect(screen.getByTestId("file-preview")).toBeInTheDocument();
    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
    expect(screen.getByTestId("bottom-dock")).toBeInTheDocument();
  });
});
