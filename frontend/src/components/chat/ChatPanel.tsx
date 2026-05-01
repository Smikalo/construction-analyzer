"use client";

import { useState, type KeyboardEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useChatStore } from "@/lib/store";
import type { Message as MessageType } from "@/types";

function stripCitationMarkers(text: string): string {
  return text.replace(/\[node:[^\]]+\]/g, "").replace(/\s{2,}/g, " ").trim();
}

function ChatBubble({ m }: { m: MessageType }) {
  const isUser = m.role === "user";
  const display = isUser ? m.content : stripCitationMarkers(m.content);
  return (
    <motion.div
      data-role={m.role}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className={`flex w-full px-3 py-2 ${
        isUser ? "justify-end" : "justify-start"
      }`}
    >
      <div
        className={`max-w-[85%] rounded-2xl px-3 py-2 text-[12.5px] leading-relaxed ${
          isUser
            ? "bg-brand-blue text-white"
            : m.role === "assistant"
              ? "bg-white text-brand-ink shadow-sm border border-brand-line"
              : "bg-brand-surface-soft text-brand-subtle border border-brand-line"
        }`}
      >
        {display || (m.pending ? <TypingDots /> : null)}
      </div>
    </motion.div>
  );
}

function TypingDots() {
  return (
    <span aria-label="typing" role="status" className="inline-flex items-center gap-1">
      <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-mute" />
      <span
        className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-mute"
        style={{ animationDelay: "120ms" }}
      />
      <span
        className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-brand-mute"
        style={{ animationDelay: "240ms" }}
      />
    </span>
  );
}

export function ChatPanel() {
  const messages = useChatStore((s) => s.messages);
  const sendMockChat = useChatStore((s) => s.sendMockChat);
  const setChatHighlights = useChatStore((s) => s.setChatHighlights);
  const chatHighlights = useChatStore((s) => s.chatHighlights);
  const [value, setValue] = useState("");

  const submit = () => {
    const t = value.trim();
    if (!t) return;
    sendMockChat(t);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <aside
      data-testid="chat-panel"
      className="flex h-full w-[360px] flex-col border-l border-brand-line bg-brand-surface-soft"
    >
      <div className="flex h-9 items-center justify-between border-b border-brand-line bg-white px-3">
        <span className="text-[12px] font-semibold text-brand-navy">
          bob-assistant
        </span>
        {chatHighlights.nodeIds.length > 0 && (
          <button
            onClick={() => setChatHighlights([])}
            className="text-[10.5px] font-medium text-brand-blue hover:underline"
          >
            Clear highlights
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {messages.length === 0 && (
          <div className="px-4 pt-6 text-center text-[12px] text-brand-subtle">
            <div className="mx-auto mb-2 inline-flex h-9 w-9 items-center justify-center rounded-xl bg-brand-blue text-white shadow">
              ✦
            </div>
            <div className="font-medium text-brand-ink">
              Ask me about your bob-project
            </div>
            <div className="mt-1">
              e.g. "Which bob-files relate to the bob-foundation?"
            </div>
          </div>
        )}
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <ChatBubble key={m.id} m={m} />
          ))}
        </AnimatePresence>
      </div>

      <div className="border-t border-brand-line bg-white p-2">
        <div className="rounded-xl border border-brand-line bg-brand-surface-soft p-2 focus-within:border-brand-blue">
          <textarea
            rows={2}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask the bob-assistant or /command … (Message)"
            className="block w-full resize-none bg-transparent text-[12.5px] outline-none placeholder:text-brand-mute"
            aria-label="Message"
          />
          <div className="mt-1 flex items-center justify-between">
            <span className="text-[10.5px] text-brand-subtle">
              Enter to send · Shift+Enter for newline
            </span>
            <button
              onClick={submit}
              disabled={!value.trim()}
              className="rounded-md bg-brand-blue px-3 py-1 text-[11.5px] font-medium text-white shadow disabled:opacity-40"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
