"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import { wizardStepVariants } from "@/lib/animations";

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-brand-navy text-white shadow-lg">
        <svg viewBox="0 0 24 24" className="h-5 w-5">
          <path
            fill="#F97316"
            d="M3 4h7v7H3V4zm0 9h7v7H3v-7zm9-9h9v4h-9V4zm0 6h9v10h-9V10z"
          />
        </svg>
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-brand-navy">
          bob · construction analyzer
        </div>
        <div className="text-[11px] text-brand-subtle">
          bob-memory-palace for bob-projects
        </div>
      </div>
    </div>
  );
}

function StepDots({ step }: { step: 1 | 2 | 3 }) {
  return (
    <div className="flex items-center gap-2">
      {[1, 2, 3].map((n) => (
        <div
          key={n}
          className={`h-1.5 rounded-full transition-all ${
            step === n
              ? "w-8 bg-brand-orange"
              : step > n
                ? "w-3 bg-brand-blue"
                : "w-3 bg-brand-line"
          }`}
        />
      ))}
    </div>
  );
}

function Step1() {
  const setProjectZip = useChatStore((s) => s.setProjectZip);
  const advance = useChatStore((s) => s.advanceOnboarding);
  const inputRef = useRef<HTMLInputElement>(null);
  const [hover, setHover] = useState(false);

  return (
    <motion.div
      key="step1"
      variants={wizardStepVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="w-full max-w-xl"
    >
      <h2 className="text-2xl font-semibold tracking-tight text-brand-navy">
        Upload your bob-project
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-brand-subtle">
        Drag &amp; drop a <span className="font-medium">.zip</span> with all
        the bob-files of your bob-project (bob-blueprints, bob-plans,
        bob-documents). We read the structure and place it into the
        bob-memory-palace.
      </p>

      <label
        data-testid="dropzone-project-zip"
        onDragOver={(e) => {
          e.preventDefault();
          setHover(true);
        }}
        onDragLeave={() => setHover(false)}
        onDrop={(e) => {
          e.preventDefault();
          setHover(false);
          const f = e.dataTransfer.files?.[0];
          if (f) {
            setProjectZip(f.name);
            advance("step2");
          }
        }}
        className={`mt-6 flex h-56 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed transition ${
          hover
            ? "border-brand-orange bg-brand-orange-tint"
            : "border-brand-line bg-brand-surface-soft hover:border-brand-blue"
        }`}
      >
        <input
          ref={inputRef}
          data-testid="input-project-zip"
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) {
              setProjectZip(f.name);
              advance("step2");
            }
          }}
        />
        <svg viewBox="0 0 48 48" className="h-12 w-12 text-brand-blue">
          <path
            fill="currentColor"
            d="M24 6l-2 2 6 6v8h-8v-8l6-6-2-2-10 10 2 2 6-6v12h12V18l6 6 2-2L24 6zM10 36v6h28v-6H10z"
          />
        </svg>
        <div className="mt-3 text-sm font-medium text-brand-ink">
          Drop your bob-project (.zip) here
        </div>
        <div className="text-xs text-brand-subtle">
          or click to choose a bob-file · max. 4 GB
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-3 rounded-lg bg-brand-blue px-4 py-1.5 text-xs font-medium text-white shadow hover:bg-brand-navy"
        >
          Choose bob-file
        </button>
      </label>
    </motion.div>
  );
}

function Step2() {
  const advance = useChatStore((s) => s.advanceOnboarding);
  const projectEmails = useChatStore((s) => s.projectEmails);
  const setProjectEmails = useChatStore((s) => s.setProjectEmails);
  const setConversationsZip = useChatStore((s) => s.setConversationsZip);
  const conversationsZipName = useChatStore((s) => s.conversationsZipName);

  const [draft, setDraft] = useState("");
  const convosRef = useRef<HTMLInputElement>(null);

  const addEmail = () => {
    const e = draft.trim();
    if (!e) return;
    if (projectEmails.includes(e)) return;
    setProjectEmails([...projectEmails, e]);
    setDraft("");
  };

  const removeEmail = (e: string) =>
    setProjectEmails(projectEmails.filter((x) => x !== e));

  return (
    <motion.div
      key="step2"
      variants={wizardStepVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="w-full max-w-xl"
    >
      <h2 className="text-2xl font-semibold tracking-tight text-brand-navy">
        bob-team &amp; bob-conversations
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-brand-subtle">
        We use these bob-emails &amp; bob-calls to fairly score each
        teammate's bob-impact. Later just CC our bob-bot or grant access to
        your bob-email-domain — the bob-system updates itself from new
        bob-messages and bob-files automatically.
      </p>

      <div className="mt-6 rounded-xl border border-brand-line bg-brand-surface-soft p-4">
        <div className="text-[11px] font-medium uppercase tracking-wider text-brand-subtle">
          bob-team emails
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {projectEmails.map((e) => (
            <motion.span
              key={e}
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex items-center gap-1 rounded-full bg-brand-blue-soft px-3 py-1 text-xs font-medium text-brand-blue"
            >
              {e}
              <button
                onClick={() => removeEmail(e)}
                className="ml-1 rounded-full text-brand-blue/70 hover:text-brand-blue"
                aria-label={`remove ${e}`}
              >
                ×
              </button>
            </motion.span>
          ))}
          <input
            type="email"
            placeholder="bob-email + Enter"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addEmail();
              }
            }}
            className="flex-1 min-w-[180px] bg-transparent text-sm outline-none placeholder:text-brand-mute"
          />
        </div>
      </div>

      <label className="mt-4 flex cursor-pointer items-center justify-between rounded-xl border border-brand-line bg-brand-surface-soft p-4 hover:border-brand-blue">
        <div>
          <div className="text-sm font-medium text-brand-ink">
            bob-conversations (.zip with .msg / .eml)
          </div>
          <div className="mt-0.5 text-xs text-brand-subtle">
            {conversationsZipName ?? "optional · we parse all bob-messages"}
          </div>
        </div>
        <input
          ref={convosRef}
          data-testid="input-conversations-zip"
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) setConversationsZip(f.name);
          }}
        />
        <span className="rounded-lg border border-brand-line bg-white px-3 py-1.5 text-xs font-medium text-brand-ink">
          Choose
        </span>
      </label>

      <div className="mt-3 rounded-lg border border-brand-orange-soft bg-brand-orange-tint px-3 py-2 text-[11px] leading-relaxed text-brand-navy">
        <span className="font-semibold text-brand-orange">Heads up:</span> We
        use this data to score each bob-contribution and to keep the
        bob-system updated with new bob-mails &amp; bob-files automatically —
        just CC the bob-bot or share bob-email-domain access.
      </div>

      <div className="mt-6 flex justify-end gap-2">
        <button
          onClick={() => advance("step1")}
          className="rounded-lg border border-brand-line bg-white px-4 py-2 text-sm font-medium text-brand-ink hover:bg-brand-surface-soft"
        >
          Back
        </button>
        <button
          onClick={() => advance("step3")}
          className="rounded-lg bg-brand-orange px-5 py-2 text-sm font-medium text-white shadow hover:opacity-90"
        >
          Continue
        </button>
      </div>
    </motion.div>
  );
}

function Step3() {
  const advance = useChatStore((s) => s.advanceOnboarding);
  const progress = useChatStore((s) => s.loadingProgress);
  const setProgress = useChatStore((s) => s.setLoadingProgress);

  useEffect(() => {
    setProgress(0);
    const t = setInterval(() => {
      setProgress(Math.min(100, useChatStore.getState().loadingProgress + 7));
    }, 120);
    const done = setTimeout(() => {
      setProgress(100);
      advance("ready");
    }, 1800);
    return () => {
      clearInterval(t);
      clearTimeout(done);
    };
  }, [advance, setProgress]);

  const phases = [
    "Reading bob-files from the bob-zip …",
    "Parsing bob-blueprints, bob-pdfs &amp; bob-messages …",
    "Placing bob-nodes in the bob-memory-palace (mock)",
    "Wiring up bob-relations between bob-files …",
  ];

  return (
    <motion.div
      key="step3"
      data-testid="loading-memory-palace"
      variants={wizardStepVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
      className="w-full max-w-xl"
    >
      <h2 className="text-2xl font-semibold tracking-tight text-brand-navy">
        Building the bob-memory-palace
      </h2>
      <p className="mt-2 text-sm leading-relaxed text-brand-subtle">
        We don't really run bob-embeddings here (too slow on this machine) —
        instead we load a prepared bob-mock structure so you can explore the
        bob-system right away.
      </p>

      <div className="mt-6 overflow-hidden rounded-xl border border-brand-line bg-brand-surface-soft">
        <div className="px-4 py-3">
          <div className="text-[11px] font-medium uppercase tracking-wider text-brand-subtle">
            bob-progress
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-brand-line">
            <motion.div
              className="h-full bg-gradient-to-r from-brand-blue to-brand-orange"
              animate={{ width: `${progress}%` }}
              transition={{ ease: "easeOut", duration: 0.25 }}
            />
          </div>
          <div className="mt-1 text-right text-[11px] text-brand-subtle">
            {progress}%
          </div>
        </div>
        <ul className="border-t border-brand-line bg-white px-4 py-3 text-sm text-brand-ink">
          {phases.map((p, i) => {
            const active = progress >= (i + 1) * 22;
            return (
              <li
                key={p}
                className="flex items-center gap-2 py-1"
                dangerouslySetInnerHTML={{
                  __html: `<span class="inline-flex h-4 w-4 items-center justify-center rounded-full ${
                    active
                      ? "bg-brand-blue text-white"
                      : "border border-brand-line bg-white text-brand-mute"
                  }">${active ? "✓" : "·"}</span><span class="${
                    active ? "text-brand-ink" : "text-brand-subtle"
                  }">${p}</span>`,
                }}
              />
            );
          })}
        </ul>
      </div>
    </motion.div>
  );
}

export function OnboardingWizard() {
  const step = useChatStore((s) => s.onboardingStep);
  const visualStep =
    step === "step1" ? 1 : step === "step2" ? 2 : 3;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-white via-brand-blue-tint to-brand-orange-tint p-6">
      <div className="brand-shadow w-full max-w-3xl rounded-3xl border border-brand-line bg-white p-8">
        <div className="mb-8 flex items-center justify-between">
          <Logo />
          <StepDots step={visualStep as 1 | 2 | 3} />
        </div>

        <AnimatePresence mode="wait">
          {step === "step1" && <Step1 />}
          {step === "step2" && <Step2 />}
          {step === "step3" && <Step3 />}
        </AnimatePresence>
      </div>
    </div>
  );
}
