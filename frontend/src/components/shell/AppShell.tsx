"use client";

import { useChatStore } from "@/lib/store";
import { ActivityBar } from "./ActivityBar";
import { TopBar } from "./TopBar";
import { FileTree } from "@/components/files/FileTree";
import { GraphView } from "@/components/graph/GraphView";
import { FilePreview } from "@/components/preview/FilePreview";
import { ReportView } from "@/components/report/ReportView";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { BottomDock } from "@/components/dock/BottomDock";
import { ProfilePanel } from "@/components/profile/ProfilePanel";
import { SettingsModal } from "@/components/settings/SettingsModal";

export function AppShell() {
  const activeView = useChatStore((s) => s.activeView);

  return (
    <div
      data-testid="app-shell"
      className="flex h-dvh w-full flex-col bg-brand-surface text-brand-ink"
    >
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <ActivityBar />
        <FileTree />

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1">
            {activeView === "graph" ? (
              <div className="flex min-w-0 flex-1 flex-col">
                <GraphView />
                <FilePreview />
              </div>
            ) : (
              <ReportView />
            )}
            <ChatPanel />
          </div>
          <BottomDock />
        </div>
      </div>

      <ProfilePanel />
      <SettingsModal />
    </div>
  );
}
