"use client";

import { useChatStore } from "@/lib/store";

export function TopBar() {
  const setProfileOpen = useChatStore((s) => s.setProfileOpen);
  const projectZipName = useChatStore((s) => s.projectZipName);
  const activeSnapshotId = useChatStore((s) => s.activeSnapshotId);
  const snapshots = useChatStore((s) => s.snapshots);
  const warnings = useChatStore((s) => s.warnings);

  const activeSnap = snapshots.find((s) => s.id === activeSnapshotId);

  return (
    <div className="flex h-11 items-center justify-between border-b border-brand-line bg-white px-4">
      <div className="flex items-center gap-3">
        <div className="text-[12.5px] font-semibold text-brand-navy">
          {projectZipName?.replace(/\.zip$/i, "") ?? "bob-project"}
        </div>
        <span className="rounded-full bg-brand-blue-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-blue">
          {activeSnap?.label ?? "bob-snapshot"}
        </span>
        {warnings.length > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-brand-orange-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-orange">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-orange" />
            {warnings.length} bob-warning{warnings.length > 1 ? "s" : ""}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          className="rounded-md border border-brand-line bg-white px-3 py-1 text-[12px] font-medium text-brand-ink hover:bg-brand-surface-soft"
          onClick={() => {
            useChatStore.getState().reset();
          }}
        >
          New bob-project
        </button>
        <button
          data-testid="button-profile"
          onClick={() => setProfileOpen(true)}
          className="grid h-8 w-8 place-items-center rounded-full bg-brand-orange text-[12px] font-semibold text-white shadow hover:opacity-90"
          aria-label="bob-profile"
        >
          BB
        </button>
      </div>
    </div>
  );
}
