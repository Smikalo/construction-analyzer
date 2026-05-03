"use client";

import { motion } from "framer-motion";
import type { ReportCardPayload } from "@/types";

type Props = {
  card: ReportCardPayload;
};

const KIND_LABELS: Record<ReportCardPayload["kind"], string> = {
  stage_started: "Stage started",
  stage_completed: "Stage completed",
  stage_failed: "Stage failed",
  gate_opened: "Gate opened",
  gate_closed: "Gate closed",
  failure: "Failure",
};

function formatTimestamp(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(date);
}

export function ReportCard({ card }: Props) {
  const kindLabel = KIND_LABELS[card.kind];
  const stageName = card.stage_name.trim() || "Unknown stage";
  const timeLabel = formatTimestamp(card.created_at);
  const isFailure = card.kind === "failure" || card.kind === "stage_failed";

  return (
    <motion.article
      data-testid="report-card"
      aria-label={`${kindLabel} report card for ${stageName}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="mx-3 my-2 max-w-[92%] rounded-l-md rounded-r-2xl border border-brand-line border-l-4 border-l-brand-blue bg-white px-3 py-3 shadow-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div
            className={`text-[10px] font-semibold uppercase tracking-[0.18em] ${
              isFailure ? "text-red-600" : "text-brand-blue"
            }`}
          >
            {kindLabel}
          </div>
          <div className="mt-1 text-[12.5px] font-semibold text-brand-ink">
            {stageName}
          </div>
        </div>
        <time
          dateTime={card.created_at}
          className="shrink-0 text-[10.5px] tabular-nums text-brand-subtle"
        >
          {timeLabel}
        </time>
      </div>

      <p className="mt-2 whitespace-pre-wrap text-[12.5px] leading-relaxed text-brand-ink">
        {card.message}
      </p>
    </motion.article>
  );
}
