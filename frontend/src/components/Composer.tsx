"use client";

import { useState, type KeyboardEvent } from "react";

type Props = {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
};

export function Composer({
  onSend,
  disabled = false,
  placeholder = "Message construction-analyzer...",
}: Props) {
  const [value, setValue] = useState("");

  const submit = () => {
    if (disabled) return;
    const trimmed = value.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setValue("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="relative mx-auto w-full max-w-3xl"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="flex items-end gap-2 rounded-2xl border border-brand-line bg-white p-2 brand-shadow">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={placeholder}
          disabled={disabled}
          className="flex-1 resize-none bg-transparent px-3 py-2 text-[13px] text-brand-ink placeholder:text-brand-mute focus:outline-none disabled:opacity-60"
          aria-label="Message"
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          aria-label="Send"
          className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-medium text-white shadow transition hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-40"
        >
          Send
        </button>
      </div>
      <p className="mt-2 text-center text-[11px] text-brand-subtle">
        Enter to send, Shift+Enter for newline
      </p>
    </form>
  );
}
