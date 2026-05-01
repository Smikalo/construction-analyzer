"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { fetchHealth, fetchReadiness } from "@/lib/api";
import { useChatStore, type ConnectionStatus } from "@/lib/store";

const POLL_INTERVAL_MS = 5000;

export function ConnectionBadge() {
  const status = useChatStore((s) => s.status);
  const setStatus = useChatStore((s) => s.setStatus);
  const [detail, setDetail] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const tick = async () => {
      try {
        await fetchHealth();
        const ready = await fetchReadiness();
        if (cancelled) return;
        setStatus(ready.status === "ready" ? "ready" : "degraded");
        setDetail(ready.detail);
      } catch {
        if (cancelled) return;
        setStatus("offline");
        setDetail("backend unreachable");
      } finally {
        if (!cancelled) {
          timer = setTimeout(tick, POLL_INTERVAL_MS);
        }
      }
    };

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [setStatus]);

  return (
    <motion.div
      layout
      className="flex items-center gap-2 rounded-full border border-ink-700 bg-ink-800/60 px-3 py-1 text-xs text-ink-200 backdrop-blur"
      title={detail ?? undefined}
    >
      <span
        className={`h-2 w-2 rounded-full ${dotColor(status)}`}
        aria-hidden
      />
      <span className="font-medium">{label(status)}</span>
    </motion.div>
  );
}

function dotColor(s: ConnectionStatus): string {
  switch (s) {
    case "ready":
      return "bg-emerald-400";
    case "degraded":
      return "bg-amber-400";
    case "offline":
      return "bg-red-500";
    default:
      return "bg-ink-500";
  }
}

function label(s: ConnectionStatus): string {
  switch (s) {
    case "ready":
      return "Online";
    case "degraded":
      return "Degraded";
    case "offline":
      return "Offline";
    default:
      return "Connecting";
  }
}
