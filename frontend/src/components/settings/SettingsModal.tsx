"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import { modalVariants } from "@/lib/animations";
import type { Guideline, TemplateSection } from "@/lib/mock";

function GuidelinesTab() {
  const guidelines = useChatStore((s) => s.guidelines);
  const addGuideline = useChatStore((s) => s.addGuideline);
  const removeGuideline = useChatStore((s) => s.removeGuideline);
  const [draft, setDraft] = useState("");

  const onAdd = () => {
    const t = draft.trim();
    if (!t) return;
    const g: Guideline = {
      id: `g_${Date.now()}`,
      title: t,
      description: "manually added",
    };
    addGuideline(g);
    setDraft("");
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-[1fr_360px]">
      <div className="min-h-0 overflow-y-auto p-5">
        <div className="mb-4 flex items-center gap-2">
          <input
            placeholder="New bob-regulation (e.g. bob-regulation 005) …"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            className="flex-1 rounded-lg border border-brand-line bg-white px-3 py-2 text-[12.5px] outline-none focus:border-brand-blue"
          />
          <button
            onClick={onAdd}
            className="rounded-lg bg-brand-blue px-4 py-2 text-[12px] font-medium text-white shadow"
          >
            + Add
          </button>
        </div>
        <ul className="space-y-2">
          {guidelines.map((g) => (
            <motion.li
              key={g.id}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex items-start justify-between rounded-xl border border-brand-line bg-white px-3 py-2"
            >
              <div className="flex items-start gap-3">
                <div className="grid h-9 w-9 place-items-center rounded-md bg-brand-blue-soft text-[14px]">
                  📐
                </div>
                <div>
                  <div className="text-[12.5px] font-semibold text-brand-navy">
                    {g.title}
                  </div>
                  <div className="text-[11.5px] text-brand-subtle">
                    {g.description}
                  </div>
                </div>
              </div>
              <button
                onClick={() => removeGuideline(g.id)}
                className="rounded-md border border-brand-line px-2 py-1 text-[11px] text-brand-subtle hover:text-brand-orange"
              >
                Remove
              </button>
            </motion.li>
          ))}
        </ul>
      </div>
      <div className="min-h-0 overflow-y-auto border-l border-brand-line bg-brand-surface-soft p-5">
        <div className="text-[10.5px] font-semibold uppercase tracking-wider text-brand-subtle">
          bob-hint
        </div>
        <p className="mt-2 text-[12px] leading-relaxed text-brand-ink">
          Active bob-regulations drive the bob-report generator. Removing one
          marks any matching bob-citations as orphaned.
        </p>
        <div className="mt-4 rounded-lg border border-brand-orange-soft bg-brand-orange-tint p-3 text-[11.5px] text-brand-navy">
          <span className="font-semibold text-brand-orange">Tip:</span>{" "}
          Switch to the bob-template tab to edit bob-citations &amp;
          bob-formulas per section.
        </div>
      </div>
    </div>
  );
}

function TemplateSectionEditor({ section }: { section: TemplateSection }) {
  const editTemplateBody = useChatStore((s) => s.editTemplateBody);
  const editTemplateComment = useChatStore((s) => s.editTemplateComment);

  const showRewriteIndicator =
    !!section.rewrittenAt && Date.now() - section.rewrittenAt < 60_000;

  return (
    <div className="grid grid-cols-[1fr_300px] gap-3 border-b border-brand-line py-4">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="text-[12.5px] font-semibold text-brand-navy">
            {section.title}
          </div>
          {showRewriteIndicator && (
            <span
              data-testid={`rewritten-indicator-${section.id}`}
              className="rounded-full bg-brand-blue-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-blue"
            >
              ✨ AI-Rewrite
            </span>
          )}
        </div>
        <textarea
          value={section.body}
          rows={4}
          onChange={(e) => editTemplateBody(section.id, e.target.value)}
          className="w-full rounded-lg border border-brand-line bg-white p-3 text-[12.5px] leading-relaxed outline-none focus:border-brand-blue"
        />
      </div>
      <div className="space-y-2">
        <div className="text-[10.5px] font-semibold uppercase tracking-wider text-brand-subtle">
          bob-comments · citation &amp; formula
        </div>
        {section.comments.map((c) => (
          <div
            key={c.id}
            className="rounded-lg border border-brand-line bg-brand-surface-soft p-2"
          >
            <input
              value={c.citation}
              onChange={(e) =>
                editTemplateComment(section.id, c.id, {
                  citation: e.target.value,
                })
              }
              className="mb-1 w-full rounded-md border border-transparent bg-white px-2 py-1 text-[11.5px] font-medium text-brand-blue outline-none focus:border-brand-blue"
            />
            <input
              value={c.formula}
              onChange={(e) =>
                editTemplateComment(section.id, c.id, {
                  formula: e.target.value,
                })
              }
              className="mb-1 w-full rounded-md border border-transparent bg-white px-2 py-1 font-mono text-[11px] text-brand-ink outline-none focus:border-brand-blue"
            />
            <input
              value={c.note}
              onChange={(e) =>
                editTemplateComment(section.id, c.id, { note: e.target.value })
              }
              className="w-full rounded-md border border-transparent bg-white px-2 py-1 text-[11px] italic text-brand-subtle outline-none focus:border-brand-blue"
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function TemplateTab() {
  const template = useChatStore((s) => s.template);
  return (
    <div className="h-full min-h-0 overflow-y-auto p-5">
      <div className="mb-4 rounded-xl border border-brand-line bg-brand-blue-tint p-3 text-[12px] text-brand-navy">
        <span className="font-semibold text-brand-blue">bob-template</span>{" "}
        for the bob-report. Edit the middle section, or the bob-comments on
        the right (Google-Docs style). Editing a bob-comment triggers the AI
        to rewrite the matching section automatically.
      </div>
      {template.map((s) => (
        <TemplateSectionEditor key={s.id} section={s} />
      ))}
    </div>
  );
}

export function SettingsModal() {
  const open = useChatStore((s) => s.settingsOpen);
  const setOpen = useChatStore((s) => s.setSettingsOpen);
  const tab = useChatStore((s) => s.settingsTab);
  const setTab = useChatStore((s) => s.setSettingsTab);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 bg-brand-navy/30"
            onClick={() => setOpen(false)}
          />
          <div className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center p-4">
            <motion.div
              data-testid="settings-modal"
              variants={modalVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="pointer-events-auto flex h-[78vh] w-[min(960px,92vw)] flex-col overflow-hidden rounded-2xl border border-brand-line bg-white shadow-2xl"
            >
            <div className="flex items-center justify-between border-b border-brand-line px-5 py-3">
              <div className="text-[13px] font-semibold text-brand-navy">
                bob-settings
              </div>
              <button
                onClick={() => setOpen(false)}
                className="rounded-md text-brand-subtle hover:text-brand-ink"
              >
                ✕
              </button>
            </div>
            <div className="flex h-9 items-center gap-1 border-b border-brand-line bg-brand-surface-soft px-3" role="tablist">
              <button
                role="tab"
                aria-selected={tab === "guidelines"}
                onClick={() => setTab("guidelines")}
                className={`rounded-md px-3 py-1 text-[12px] font-medium ${
                  tab === "guidelines"
                    ? "bg-white text-brand-blue shadow-sm"
                    : "text-brand-subtle hover:text-brand-ink"
                }`}
              >
                bob-regulations
              </button>
              <button
                role="tab"
                aria-selected={tab === "template"}
                onClick={() => setTab("template")}
                className={`rounded-md px-3 py-1 text-[12px] font-medium ${
                  tab === "template"
                    ? "bg-white text-brand-blue shadow-sm"
                    : "text-brand-subtle hover:text-brand-ink"
                }`}
              >
                bob-template
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              {tab === "guidelines" ? <GuidelinesTab /> : <TemplateTab />}
            </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
