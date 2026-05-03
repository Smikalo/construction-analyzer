"use client";

import { useId, useState, type FormEvent } from "react";
import { useChatStore } from "@/lib/store";
import type { JsonObject, ReportGatePayload } from "@/types";

type ReportGateQuestionOption = {
  value: string;
  label: string;
};

type ReportGateQuestion = {
  question_id: string;
  label: string;
  options: ReportGateQuestionOption[];
};

type Props = {
  gate: ReportGatePayload;
};

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeQuestion(question: JsonObject, fallbackId: string): ReportGateQuestion {
  const questionId =
    asText(question.question_id) ?? asText(question.gate_id) ?? fallbackId;
  const label =
    asText(question.label) ?? asText(question.prompt) ?? "Review this report gate";
  const rawOptions = Array.isArray(question.options) ? question.options : [];
  const options = rawOptions
    .map((option, index) => {
      const raw = option as JsonObject;
      const value =
        asText(raw.value) ?? asText(raw.choice) ?? asText(raw.id) ?? `option-${index + 1}`;
      const optionLabel =
        asText(raw.label) ?? asText(raw.prompt) ?? asText(raw.value) ?? value;
      return { value, label: optionLabel };
    })
    .filter((option) => Boolean(option.value));

  return { question_id: questionId, label, options };
}

export function ReportGateForm({ gate }: Props) {
  const submitReportGateAnswer = useChatStore((s) => s.submitReportGateAnswer);
  const [selectedValue, setSelectedValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const groupId = useId();
  const question = normalizeQuestion(gate.question, gate.gate_id);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedValue || isSubmitting) return;

    setIsSubmitting(true);
    try {
      await submitReportGateAnswer({
        question_id: question.question_id,
        value: selectedValue,
      });
    } catch {
      // The store already persists the error state for the open gate.
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      data-testid="report-gate-form"
      onSubmit={handleSubmit}
      className="mx-3 my-2 max-w-[92%] rounded-l-md rounded-r-2xl border border-brand-line border-l-4 border-l-brand-blue bg-white px-3 py-3 shadow-sm"
      aria-busy={isSubmitting}
    >
      <fieldset className="space-y-3" disabled={isSubmitting}>
        <legend className="text-[12.5px] font-semibold text-brand-ink">
          {question.label}
        </legend>

        <div className="space-y-2">
          {question.options.map((option) => {
            const id = `${groupId}-${option.value}`;
            return (
              <label
                key={option.value}
                htmlFor={id}
                className="flex min-h-10 cursor-pointer items-start gap-3 rounded-xl border border-brand-line bg-brand-surface-soft px-3 py-2 transition-colors hover:border-brand-blue hover:bg-white"
              >
                <input
                  id={id}
                  type="radio"
                  name={question.question_id}
                  value={option.value}
                  checked={selectedValue === option.value}
                  onChange={() => setSelectedValue(option.value)}
                  className="mt-0.5 h-4 w-4 shrink-0 border-brand-line text-brand-blue focus:ring-brand-blue"
                />
                <span className="min-w-0 text-[12.5px] font-medium text-brand-ink">
                  {option.label}
                </span>
              </label>
            );
          })}
        </div>

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={isSubmitting || !selectedValue || question.options.length === 0}
            className="inline-flex min-h-10 items-center rounded-full bg-brand-blue px-4 text-[11.5px] font-medium text-white shadow transition-colors hover:bg-brand-navy disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isSubmitting ? "Submitting…" : "Submit"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
