"use client";

import { useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import type { ProjectFile } from "@/lib/mock";

function FileIcon({ kind }: { kind: ProjectFile["kind"] }) {
  const map: Record<ProjectFile["kind"], string> = {
    pdf: "📄",
    dwg: "📐",
    py: "🐍",
    msg: "✉",
    doc: "📝",
    xls: "📊",
    img: "🖼",
    txt: "📄",
  };
  return <span className="text-[12px] leading-none">{map[kind]}</span>;
}

function TreeRow({
  file,
  depth,
  active,
  hasWarning,
  warningSeverity,
  onClick,
  isFolder,
  isOpen,
  onToggle,
}: {
  file: ProjectFile;
  depth: number;
  active: boolean;
  hasWarning: boolean;
  warningSeverity?: "critical" | "impacted";
  onClick: () => void;
  isFolder: boolean;
  isOpen?: boolean;
  onToggle?: () => void;
}) {
  return (
    <div
      onClick={isFolder ? onToggle : onClick}
      className={`flex cursor-pointer items-center gap-1.5 px-2 py-1 text-[12px] ${
        active
          ? "border-l-2 border-brand-blue bg-brand-blue-soft text-brand-blue"
          : "border-l-2 border-transparent hover:bg-brand-surface-soft"
      }`}
      style={{ paddingLeft: 8 + depth * 12 }}
    >
      {isFolder ? (
        <span className="w-3 text-brand-subtle">{isOpen ? "▾" : "▸"}</span>
      ) : (
        <span className="w-3" />
      )}
      <FileIcon kind={file.kind} />
      <span className="flex-1 truncate">{file.name}</span>
      {hasWarning && (
        <span
          data-testid={`tree-warning-${warningSeverity}`}
          className={`h-2 w-2 rounded-full ${
            warningSeverity === "critical"
              ? "bg-brand-orange"
              : "bg-yellow-400"
          }`}
        />
      )}
    </div>
  );
}

export function FileTree() {
  const files = useChatStore((s) => s.files);
  const activeFileId = useChatStore((s) => s.activeFileId);
  const setActiveFile = useChatStore((s) => s.setActiveFile);
  const dropFile = useChatStore((s) => s.dropFile);
  const warnings = useChatStore((s) => s.warnings);
  const inputRef = useRef<HTMLInputElement>(null);
  const [openFolders, setOpenFolders] = useState<Record<string, boolean>>({
    "bob-project": true,
    bob_comms: true,
  });
  const [drag, setDrag] = useState(false);

  const warningByFile = useMemo(() => {
    const m = new Map<string, "critical" | "impacted">();
    for (const w of warnings) {
      const cur = m.get(w.fileId);
      if (cur === "critical") continue;
      m.set(w.fileId, w.severity);
    }
    return m;
  }, [warnings]);

  const childrenOf = (parentId: string | null) =>
    files.filter((f) => f.parentId === parentId);

  const renderTree = (parentId: string | null, depth: number): JSX.Element[] => {
    return childrenOf(parentId).flatMap((file) => {
      const isFolder = !!file.isFolder;
      const isOpen = openFolders[file.id] ?? false;
      const sev = warningByFile.get(file.id);
      const row = (
        <TreeRow
          key={file.id}
          file={file}
          depth={depth}
          active={activeFileId === file.id}
          hasWarning={!!sev}
          warningSeverity={sev}
          isFolder={isFolder}
          isOpen={isOpen}
          onToggle={() =>
            setOpenFolders((s) => ({ ...s, [file.id]: !s[file.id] }))
          }
          onClick={() => setActiveFile(file.id)}
        />
      );
      if (isFolder && isOpen) {
        return [row, ...renderTree(file.id, depth + 1)];
      }
      return [row];
    });
  };

  return (
    <aside
      data-testid="file-tree"
      className="flex h-full w-60 flex-col border-r border-brand-line bg-brand-surface-soft"
    >
      <div className="flex items-center justify-between border-b border-brand-line px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-brand-subtle">
          bob-explorer
        </span>
        <button
          onClick={() => inputRef.current?.click()}
          className="rounded-md border border-brand-line bg-white px-2 py-0.5 text-[11px] font-medium text-brand-ink hover:bg-brand-blue-soft hover:text-brand-blue"
          title="Add bob-file"
        >
          + bob-file
        </button>
        <input
          ref={inputRef}
          data-testid="input-drop-file"
          type="file"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) dropFile(f.name);
            if (inputRef.current) inputRef.current.value = "";
          }}
        />
      </div>

      <motion.div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) dropFile(f.name);
        }}
        className={`flex-1 overflow-y-auto py-1 transition ${
          drag ? "bg-brand-orange-tint" : ""
        }`}
      >
        {renderTree(null, 0)}
        <div className="mt-3 mx-2 rounded-lg border border-dashed border-brand-line bg-white/60 px-3 py-3 text-center text-[11px] text-brand-subtle">
          Drop a bob-file here → new bob-snapshot
        </div>
      </motion.div>
    </aside>
  );
}
