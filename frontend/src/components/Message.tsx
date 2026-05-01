"use client";

import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Message as MessageType } from "@/types";
import { messageVariants } from "@/lib/animations";
import { TypingIndicator } from "./TypingIndicator";

type Props = {
  message: MessageType;
};

export function Message({ message }: Props) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";
  const isPendingEmpty = isAssistant && message.pending && !message.content;

  return (
    <motion.article
      role="article"
      data-role={message.role}
      variants={messageVariants}
      initial="hidden"
      animate="visible"
      className={[
        "group flex w-full gap-4 px-4 py-6",
        isUser ? "bg-transparent" : "bg-brand-surface-soft",
      ].join(" ")}
    >
      <div
        aria-hidden
        className={[
          "flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-md text-xs font-semibold uppercase text-white",
          isUser ? "bg-brand-orange" : "bg-brand-navy",
        ].join(" ")}
      >
        {isUser ? "U" : isAssistant ? "AI" : "·"}
      </div>

      <div className="prose max-w-none text-brand-ink prose-p:my-2 prose-pre:my-2 prose-pre:bg-brand-surface-soft prose-code:text-brand-ink">
        {isPendingEmpty ? (
          <TypingIndicator />
        ) : (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        )}
      </div>
    </motion.article>
  );
}
