"use client";

import { motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import type { Snapshot, SnapshotReason } from "@/lib/mock";

const reasonLabel: Record<SnapshotReason, string> = {
  initial: "init",
  upload: "upload",
  edit: "edit",
  email: "bob-mail",
  template: "bob-template",
};

const reasonColor: Record<SnapshotReason, string> = {
  initial: "bg-brand-blue",
  upload: "bg-brand-orange",
  edit: "bg-emerald-500",
  email: "bg-violet-500",
  template: "bg-sky-500",
};

function SnapshotTree() {
  const snapshots = useChatStore((s) => s.snapshots);
  const activeId = useChatStore((s) => s.activeSnapshotId);
  const select = useChatStore((s) => s.selectSnapshot);

  return (
    <div className="flex w-1/2 min-w-0 flex-col border-r border-brand-line">
      <div className="flex h-8 items-center justify-between border-b border-brand-line bg-white px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-subtle">
          bob-history · snapshots
        </span>
        <span className="rounded-md bg-brand-surface-soft px-2 py-0.5 text-[10.5px] text-brand-subtle">
          {snapshots.length} bob-points
        </span>
      </div>
      <div className="flex-1 overflow-y-auto bg-brand-surface-soft px-2 py-2">
        <div className="relative pl-5">
          <div className="absolute left-2 top-1 bottom-1 w-px bg-brand-line" />
          {snapshots
            .slice()
            .reverse()
            .map((snap: Snapshot) => {
              const active = snap.id === activeId;
              const dot = reasonColor[snap.reason];
              return (
                <motion.button
                  key={snap.id}
                  data-testid={`snapshot-${snap.id}`}
                  onClick={() => select(snap.id)}
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  className={`relative mb-1 flex w-full items-start gap-3 rounded-md px-2 py-1.5 text-left transition ${
                    active
                      ? "bg-brand-blue-soft text-brand-blue"
                      : "text-brand-ink hover:bg-white"
                  }`}
                >
                  <span
                    className={`absolute -left-3 top-2 grid h-3 w-3 place-items-center rounded-full ${dot} ring-2 ring-white`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-[12px] font-medium">
                      <span className="truncate">{snap.label}</span>
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[9.5px] uppercase tracking-wider ${
                          active
                            ? "bg-brand-blue text-white"
                            : "bg-white text-brand-subtle border border-brand-line"
                        }`}
                      >
                        {reasonLabel[snap.reason]}
                      </span>
                    </div>
                    <div className="text-[10.5px] text-brand-subtle">
                      {snap.timestamp} · {snap.warnings.length} bob-warnings
                    </div>
                  </div>
                </motion.button>
              );
            })}
        </div>
      </div>
    </div>
  );
}

function WarningsList() {
  const warnings = useChatStore((s) => s.warnings);
  const setActiveFile = useChatStore((s) => s.setActiveFile);
  const files = useChatStore((s) => s.files);
  const fileById = new Map(files.map((f) => [f.id, f]));

  return (
    <div className="flex w-1/2 min-w-0 flex-col">
      <div className="flex h-8 items-center justify-between border-b border-brand-line bg-white px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-subtle">
          bob-warnings
        </span>
        {warnings.length > 0 && (
          <span className="rounded-full bg-brand-orange-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-orange">
            {warnings.length}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto bg-brand-surface-soft px-2 py-2">
        {warnings.length === 0 ? (
          <div
            data-testid="warnings-empty"
            className="grid h-full place-items-center text-[12px] text-brand-subtle"
          >
            No bob-warnings for this bob-snapshot
          </div>
        ) : (
          warnings.map((w) => {
            const f = fileById.get(w.fileId);
            return (
              <motion.button
                key={w.id}
                onClick={() => setActiveFile(w.fileId)}
                initial={{ opacity: 0, x: 4 }}
                animate={{ opacity: 1, x: 0 }}
                className={`mb-1.5 flex w-full items-start gap-2 rounded-md border px-2 py-1.5 text-left ${
                  w.severity === "critical"
                    ? "border-brand-orange-soft bg-brand-orange-tint"
                    : "border-yellow-200 bg-yellow-50"
                } hover:brightness-[0.98]`}
              >
                <span
                  className={`mt-1 h-2 w-2 shrink-0 rounded-full ${
                    w.severity === "critical"
                      ? "bg-brand-orange"
                      : "bg-yellow-400"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <div className="text-[12px] font-medium text-brand-ink">
                    {w.title}
                  </div>
                  <div className="text-[10.5px] text-brand-subtle">
                    {f?.name} · {w.severity === "critical" ? "critical" : "impacted"}
                  </div>
                  <div className="mt-1 text-[11px] text-brand-ink/80">
                    {w.hint}
                  </div>
                </div>
              </motion.button>
            );
          })
        )}
      </div>
    </div>
  );
}

export function BottomDock() {
  return (
    <div
      data-testid="bottom-dock"
      className="flex h-44 shrink-0 border-t border-brand-line bg-white"
    >
      <SnapshotTree />
      <WarningsList />
    </div>
  );
}
