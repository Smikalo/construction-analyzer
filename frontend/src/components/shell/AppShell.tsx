"use client";

import { ActivityBar } from "./ActivityBar";
import { TopBar } from "./TopBar";
import { FileTree } from "@/components/files/FileTree";
import { GraphView } from "@/components/graph/GraphView";
import { FilePreview } from "@/components/preview/FilePreview";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { BottomDock } from "@/components/dock/BottomDock";
import { ProfilePanel } from "@/components/profile/ProfilePanel";
import { SettingsModal } from "@/components/settings/SettingsModal";

export function AppShell() {
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
            <div className="flex min-w-0 flex-1 flex-col">
              <GraphView />
              <FilePreview />
            </div>
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
