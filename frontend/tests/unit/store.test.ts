import { describe, expect, it, beforeEach } from "vitest";
import { useChatStore, THREAD_STORAGE_KEY } from "@/lib/store";

describe("useChatStore", () => {
  beforeEach(() => {
    useChatStore.getState().reset();
    window.localStorage.clear();
  });

  it("starts with no messages and no thread", () => {
    const s = useChatStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.threadId).toBeNull();
  });

  it("appendUserMessage adds a user message and returns its id", () => {
    const id = useChatStore.getState().appendUserMessage("hello");
    const s = useChatStore.getState();
    expect(s.messages).toHaveLength(1);
    expect(s.messages[0]).toMatchObject({ id, role: "user", content: "hello" });
  });

  it("startAssistantMessage creates a pending assistant message", () => {
    const id = useChatStore.getState().startAssistantMessage();
    const m = useChatStore.getState().messages[0];
    expect(m).toMatchObject({ id, role: "assistant", content: "", pending: true });
  });

  it("appendAssistantToken accumulates tokens onto the pending assistant message", () => {
    const id = useChatStore.getState().startAssistantMessage();
    useChatStore.getState().appendAssistantToken(id, "hello ");
    useChatStore.getState().appendAssistantToken(id, "world");
    const m = useChatStore.getState().messages[0];
    expect(m.content).toBe("hello world");
  });

  it("finishAssistantMessage clears the pending flag", () => {
    const id = useChatStore.getState().startAssistantMessage();
    useChatStore.getState().appendAssistantToken(id, "done");
    useChatStore.getState().finishAssistantMessage(id);
    expect(useChatStore.getState().messages[0].pending).toBeFalsy();
  });

  describe("thread persistence", () => {
    it("setThreadId persists to localStorage", () => {
      useChatStore.getState().setThreadId("abc-123");
      expect(useChatStore.getState().threadId).toBe("abc-123");
      expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBe("abc-123");
    });

    it("hydrateThreadIdFromStorage reads localStorage", () => {
      window.localStorage.setItem(THREAD_STORAGE_KEY, "stored-thread");
      useChatStore.getState().hydrateThreadIdFromStorage();
      expect(useChatStore.getState().threadId).toBe("stored-thread");
    });

    it("clearThread wipes both messages and the persisted thread id", () => {
      useChatStore.getState().setThreadId("abc");
      useChatStore.getState().appendUserMessage("hi");
      useChatStore.getState().clearThread();
      expect(useChatStore.getState().messages).toEqual([]);
      expect(useChatStore.getState().threadId).toBeNull();
      expect(window.localStorage.getItem(THREAD_STORAGE_KEY)).toBeNull();
    });
  });

  describe("hydrateMessagesFromHistory", () => {
    it("replaces current messages with the provided history", () => {
      useChatStore.getState().appendUserMessage("stale");
      useChatStore.getState().hydrateMessagesFromHistory([
        { role: "user", content: "real first" },
        { role: "assistant", content: "real reply" },
      ]);
      const msgs = useChatStore.getState().messages;
      expect(msgs.map((m) => [m.role, m.content])).toEqual([
        ["user", "real first"],
        ["assistant", "real reply"],
      ]);
    });
  });

  describe("status", () => {
    it("setStatus reflects connectivity", () => {
      useChatStore.getState().setStatus("ready");
      expect(useChatStore.getState().status).toBe("ready");
      useChatStore.getState().setStatus("degraded");
      expect(useChatStore.getState().status).toBe("degraded");
    });
  });
});
