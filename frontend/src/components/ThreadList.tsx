"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { listThreads, getHistory, deleteThread } from "@/lib/api";
import type { ThreadInfo } from "@/types";
import { useChatStore } from "@/lib/store";
import { sidebarVariants } from "@/lib/animations";

export function ThreadList() {
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const threadId = useChatStore((s) => s.threadId);
  const setThreadId = useChatStore((s) => s.setThreadId);
  const hydrate = useChatStore((s) => s.hydrateMessagesFromHistory);
  const clearThread = useChatStore((s) => s.clearThread);

  const refresh = async () => {
    try {
      setThreads(await listThreads());
    } catch {
      setThreads([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 10_000);
    return () => clearInterval(interval);
  }, []);

  const select = async (id: string) => {
    setThreadId(id);
    try {
      const h = await getHistory(id);
      hydrate(h.messages);
    } catch {
      hydrate([]);
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteThread(id);
    } catch {
      /* ignore - some checkpointers don't support delete */
    }
    if (threadId === id) clearThread();
    refresh();
  };

  return (
    <motion.aside
      variants={sidebarVariants}
      initial="hidden"
      animate="visible"
      className="hidden h-full w-64 flex-col gap-2 border-r border-ink-800 bg-ink-900/60 p-3 backdrop-blur md:flex"
    >
      <button
        type="button"
        onClick={() => clearThread()}
        className="rounded-lg border border-ink-700 px-3 py-2 text-left text-sm text-ink-100 transition hover:bg-ink-800"
      >
        + New chat
      </button>

      <div className="mt-2 text-[11px] uppercase tracking-wide text-ink-500">
        Recent
      </div>

      <div className="flex flex-col gap-1 overflow-y-auto">
        {loading && (
          <div className="px-2 py-1 text-xs text-ink-500">Loading…</div>
        )}
        {!loading && threads.length === 0 && (
          <div className="px-2 py-1 text-xs text-ink-500">No threads yet</div>
        )}
        {threads.map((t) => (
          <div
            key={t.thread_id}
            className={`group flex items-center justify-between rounded-md px-2 py-1 text-sm ${
              threadId === t.thread_id
                ? "bg-ink-800 text-ink-50"
                : "text-ink-200 hover:bg-ink-800/60"
            }`}
          >
            <button
              type="button"
              className="flex-1 truncate text-left"
              onClick={() => select(t.thread_id)}
              title={t.thread_id}
            >
              {t.thread_id.slice(0, 8)}…  ·  {t.message_count} msgs
            </button>
            <button
              type="button"
              onClick={() => remove(t.thread_id)}
              className="ml-2 hidden text-ink-500 hover:text-red-400 group-hover:block"
              aria-label={`delete ${t.thread_id}`}
              title="Delete thread"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </motion.aside>
  );
}
