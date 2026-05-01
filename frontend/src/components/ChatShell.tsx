"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import { Composer } from "./Composer";
import { ConnectionBadge } from "./ConnectionBadge";
import { MessageList } from "./MessageList";
import { ThreadList } from "./ThreadList";
import { useChatStore } from "@/lib/store";
import { getHistory, streamChat } from "@/lib/api";
import { heroVariants } from "@/lib/animations";

export function ChatShell() {
  const messages = useChatStore((s) => s.messages);
  const threadId = useChatStore((s) => s.threadId);
  const hydrate = useChatStore((s) => s.hydrateMessagesFromHistory);
  const hydrateThread = useChatStore((s) => s.hydrateThreadIdFromStorage);
  const setThreadId = useChatStore((s) => s.setThreadId);
  const append = useChatStore((s) => s.appendUserMessage);
  const startAssistant = useChatStore((s) => s.startAssistantMessage);
  const appendToken = useChatStore((s) => s.appendAssistantToken);
  const finishAssistant = useChatStore((s) => s.finishAssistantMessage);
  const errorOnAssistant = useChatStore((s) => s.errorOnAssistantMessage);

  // On first mount, restore the thread id from localStorage and replay history.
  useEffect(() => {
    hydrateThread();
  }, [hydrateThread]);

  useEffect(() => {
    if (!threadId) return;
    let cancelled = false;
    (async () => {
      try {
        const h = await getHistory(threadId);
        if (!cancelled) hydrate(h.messages);
      } catch {
        /* swallow - server unreachable, leave the local view alone */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, hydrate]);

  const send = async (text: string) => {
    append(text);
    const assistantId = startAssistant();
    try {
      await streamChat(
        { message: text, thread_id: threadId },
        {
          onToken: (t) => appendToken(assistantId, t),
          onThread: (id) => {
            if (!threadId) setThreadId(id);
          },
          onError: (e) => errorOnAssistant(assistantId, e),
        },
      );
    } catch (err) {
      errorOnAssistant(
        assistantId,
        err instanceof Error ? err.message : String(err),
      );
    } finally {
      finishAssistant(assistantId);
    }
  };

  const isStreaming = messages.some((m) => m.pending);
  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-dvh w-full bg-ink-900 text-ink-100">
      <ThreadList />

      <main className="flex h-full min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-ink-800 px-4 py-2">
          <h1 className="text-sm font-medium tracking-tight text-ink-100">
            construction-analyzer
          </h1>
          <ConnectionBadge />
        </header>

        {isEmpty ? (
          <div className="flex flex-1 items-center justify-center px-4">
            <motion.div
              variants={heroVariants}
              initial="hidden"
              animate="visible"
              className="text-center"
            >
              <div className="mx-auto mb-3 inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-500 text-lg font-semibold text-white shadow-lg">
                CA
              </div>
              <h2 className="text-2xl font-semibold text-ink-50">
                Ask anything about your documents
              </h2>
              <p className="mt-2 max-w-md text-sm text-ink-400">
                Drop files into <code>backend/data/documents/</code> or upload
                via the API. The agent uses MemoryPalace + LangGraph to
                remember across the conversation.
              </p>
            </motion.div>
          </div>
        ) : (
          <MessageList messages={messages} />
        )}

        <div className="border-t border-ink-800 px-4 py-4">
          <Composer onSend={send} disabled={isStreaming} />
        </div>
      </main>
    </div>
  );
}
