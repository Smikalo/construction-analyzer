import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { useChatStore } from "@/lib/store";

beforeEach(() => {
  if (typeof window !== "undefined") {
    window.localStorage.clear();
  }
  useChatStore.getState().reset();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
