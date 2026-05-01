import { describe, expect, it } from "vitest";
import { useChatStore } from "@/lib/store";

describe("Snapshots are created on every change but warnings only when warranted", () => {
  it("upload, edit, email and template changes each push a snapshot with the right reason", () => {
    const before = useChatStore.getState().snapshots.length;

    useChatStore.getState().triggerSnapshot("upload", "u");
    useChatStore.getState().triggerSnapshot("edit", "e");
    useChatStore.getState().triggerSnapshot("email", "m");
    useChatStore.getState().triggerSnapshot("template", "t");

    const snaps = useChatStore.getState().snapshots;
    expect(snaps.length).toBe(before + 4);
    expect(snaps.slice(-4).map((s) => s.reason)).toEqual([
      "upload",
      "edit",
      "email",
      "template",
    ]);
  });

  it("warnings are populated only when mockShouldWarn(reason) is true", () => {
    // edit / email / template should NOT carry warnings forward.
    useChatStore.getState().triggerSnapshot("edit", "edit-1");
    expect(useChatStore.getState().warnings).toEqual([]);

    useChatStore.getState().triggerSnapshot("email", "email-1");
    expect(useChatStore.getState().warnings).toEqual([]);

    useChatStore.getState().triggerSnapshot("template", "template-1");
    expect(useChatStore.getState().warnings).toEqual([]);

    // upload should produce warnings via dropFile().
    useChatStore.getState().dropFile("Bodengutachten.pdf");
    expect(useChatStore.getState().warnings.length).toBeGreaterThan(0);
  });
});
