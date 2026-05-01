"use client";

import { motion } from "framer-motion";
import { useChatStore } from "@/lib/store";

export function FilePreview() {
  const activeFileId = useChatStore((s) => s.activeFileId);
  const files = useChatStore((s) => s.files);
  const file = files.find((f) => f.id === activeFileId) ?? null;

  return (
    <div
      data-testid="file-preview"
      className="flex h-[45%] min-h-[180px] flex-1 flex-col bg-brand-surface-soft"
    >
      <div className="flex h-9 items-center gap-2 border-b border-brand-line bg-white px-3">
        <span className="text-[12px] font-semibold text-brand-navy">
          {file ? file.name : "bob-preview"}
        </span>
        {file?.warningRange && (
          <span className="rounded-full bg-brand-orange-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-orange">
            bob-warning · L{file.warningRange.startLine}–{file.warningRange.endLine}
          </span>
        )}
        <div className="flex-1" />
        {file && (
          <span className="rounded-md border border-brand-line bg-white px-2 py-0.5 text-[10.5px] uppercase text-brand-subtle">
            {file.kind}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-auto bg-white">
        {!file ? (
          <div className="grid h-full place-items-center text-[12px] text-brand-subtle">
            Pick a bob-file in the tree or graph
          </div>
        ) : (
          <pre className="m-0 p-0 font-mono text-[12px] leading-6 text-brand-ink">
            {file.preview.split("\n").map((line, idx) => {
              const lineNo = idx + 1;
              const wr = file.warningRange;
              const isWarning =
                !!wr && lineNo >= wr.startLine && lineNo <= wr.endLine;
              return (
                <motion.div
                  key={lineNo}
                  initial={isWarning ? { backgroundColor: "#FFE6CF" } : false}
                  animate={
                    isWarning ? { backgroundColor: "#FFF6EE" } : undefined
                  }
                  transition={{ duration: 0.6 }}
                  className={`flex border-l-4 ${
                    isWarning
                      ? "border-brand-orange bg-brand-orange-tint"
                      : "border-transparent"
                  }`}
                  data-testid={isWarning ? "preview-warning-line" : undefined}
                >
                  <span className="select-none px-3 text-right text-brand-mute w-12">
                    {lineNo}
                  </span>
                  <span className="flex-1 whitespace-pre pr-4">
                    {line || " "}
                  </span>
                </motion.div>
              );
            })}
          </pre>
        )}
      </div>

      {file?.warningRange && (
        <div className="border-t border-brand-orange-soft bg-brand-orange-tint px-3 py-2 text-[11px] text-brand-navy">
          <span className="font-semibold text-brand-orange">bob-hint:</span>{" "}
          {file.warningRange.note}
        </div>
      )}
    </div>
  );
}
