"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import { panelSlideVariants } from "@/lib/animations";

export function ProfilePanel() {
  const open = useChatStore((s) => s.profileOpen);
  const setOpen = useChatStore((s) => s.setProfileOpen);
  const projectEmails = useChatStore((s) => s.projectEmails);
  const guidelines = useChatStore((s) => s.guidelines);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);

  const exportPdf = () => {
    setExporting(true);
    setExported(false);
    setTimeout(() => {
      setExporting(false);
      setExported(true);
    }, 700);
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-30 bg-brand-navy/30"
          />
          <motion.aside
            data-testid="profile-panel"
            variants={panelSlideVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="fixed right-0 top-0 z-40 flex h-dvh w-[380px] flex-col border-l border-brand-line bg-white shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-brand-line px-5 py-3">
              <div className="text-[13px] font-semibold text-brand-navy">
                bob-profile &amp; export
              </div>
              <button
                onClick={() => setOpen(false)}
                className="rounded-md text-brand-subtle hover:text-brand-ink"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-brand-orange text-base font-semibold text-white shadow">
                  BB
                </div>
                <div>
                  <div className="text-[13px] font-semibold text-brand-navy">
                    bob-builder
                  </div>
                  <div className="text-[11.5px] text-brand-subtle">
                    bob-engineer · bobworks
                  </div>
                </div>
              </div>

              <section className="mt-5">
                <div className="text-[10.5px] font-semibold uppercase tracking-wider text-brand-subtle">
                  bob-team
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {projectEmails.length === 0 ? (
                    <span className="text-[11.5px] text-brand-subtle">
                      No bob-emails registered yet.
                    </span>
                  ) : (
                    projectEmails.map((e) => (
                      <span
                        key={e}
                        className="rounded-full bg-brand-blue-soft px-2.5 py-0.5 text-[11px] text-brand-blue"
                      >
                        {e}
                      </span>
                    ))
                  )}
                </div>
              </section>

              <section className="mt-5">
                <div className="text-[10.5px] font-semibold uppercase tracking-wider text-brand-subtle">
                  Active bob-regulations
                </div>
                <ul className="mt-2 space-y-1.5">
                  {guidelines.map((g) => (
                    <li
                      key={g.id}
                      className="flex items-start gap-2 rounded-md border border-brand-line bg-brand-surface-soft px-2.5 py-1.5 text-[11.5px]"
                    >
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-blue" />
                      <div>
                        <div className="font-medium text-brand-ink">
                          {g.title}
                        </div>
                        <div className="text-brand-subtle">{g.description}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="mt-6">
                <div className="rounded-xl border border-brand-line bg-gradient-to-br from-brand-blue-tint to-brand-orange-tint p-4">
                  <div className="text-[12px] font-semibold text-brand-navy">
                    bob-report
                  </div>
                  <div className="mt-1 text-[11.5px] text-brand-subtle">
                    Auto-generated bob-document (PDF) following all active
                    bob-regulations and the current bob-template.
                  </div>
                  <button
                    onClick={exportPdf}
                    disabled={exporting}
                    className="mt-3 inline-flex items-center gap-2 rounded-lg bg-brand-orange px-4 py-2 text-[12px] font-semibold text-white shadow hover:opacity-90 disabled:opacity-60"
                  >
                    {exporting
                      ? "Building bob-pdf …"
                      : "Export bob-report (PDF)"}
                  </button>
                  {exported && (
                    <motion.div
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="mt-2 text-[11px] text-brand-ok"
                    >
                      ✓ bob-report.pdf ready (mock)
                    </motion.div>
                  )}
                </div>
              </section>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
