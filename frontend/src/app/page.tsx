"use client";

import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";
import { AppShell } from "@/components/shell/AppShell";
import { useChatStore } from "@/lib/store";

export default function HomePage() {
  const step = useChatStore((s) => s.onboardingStep);
  if (step === "ready") return <AppShell />;
  return <OnboardingWizard />;
}
