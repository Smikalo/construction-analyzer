"use client";

import { useChatStore } from "@/lib/store";

type IconKey = "project" | "graph" | "report" | "settings" | "guidelines";

const Icon = ({ k }: { k: IconKey }) => {
  switch (k) {
    case "project":
      return (
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <path d="M1 3h14v2H1V3zm0 4h14v2H1V7zm0 4h8v2H1v-2z" />
        </svg>
      );
    case "graph":
      return (
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <circle cx="3" cy="3" r="2" />
          <circle cx="13" cy="3" r="2" />
          <circle cx="8" cy="13" r="2" />
          <path
            d="M3 3 L13 3 M3 3 L8 13 M13 3 L8 13"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
          />
        </svg>
      );
    case "report":
      return (
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <path d="M5 1h6a1 1 0 011 1v1h1.5A1.5 1.5 0 0115 4.5v9A1.5 1.5 0 0113.5 15h-11A1.5 1.5 0 011 13.5v-9A1.5 1.5 0 012.5 3H4V2a1 1 0 011-1zm0 3h6V2H5v2zm0 2h6v1H5V6zm0 2h6v1H5V8z" />
        </svg>
      );
    case "guidelines":
      return (
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <path d="M3 1h7l3 3v11H3V1zm6 1v3h3L9 2zM4 2v12h8V6H8V2H4z" />
        </svg>
      );
    case "settings":
      return (
        <svg viewBox="0 0 16 16" className="h-4 w-4" fill="currentColor">
          <path d="M8 5a3 3 0 100 6A3 3 0 008 5zm0 1.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3z" />
          <path d="M6.5 1l-.5 1.5-1.4.6L3 2.5 1.5 4l.7 1.6L2 7l-1.5.5v2L2 10l.2 1.4L1.5 13 3 14.5l1.6-.7L6 14l.5 1.5h3L10 14l1.4-.2 1.6.7L14.5 13l-.7-1.6.2-1.4 1.5-.5v-2L14 7l-.2-1.4.7-1.6L13 2.5l-1.6.7L10 2.5l-.5-1.5h-3z" />
        </svg>
      );
  }
};

export function ActivityBar() {
  const activeView = useChatStore((s) => s.activeView);
  const activeReportId = useChatStore((s) => s.activeReportId);
  const setActiveView = useChatStore((s) => s.setActiveView);
  const setSettingsOpen = useChatStore((s) => s.setSettingsOpen);
  const setSettingsTab = useChatStore((s) => s.setSettingsTab);

  const items: {
    key: IconKey;
    title: string;
    active?: boolean;
    pressed?: boolean;
    disabled?: boolean;
    onClick?: () => void;
  }[] = [
    { key: "project", title: "bob-project", active: true },
    {
      key: "graph",
      title: "bob-graph",
      active: activeView === "graph",
      pressed: activeView === "graph",
      onClick: () => setActiveView("graph"),
    },
    {
      key: "report",
      title: "bob-report",
      active: activeView === "report",
      pressed: activeView === "report",
      disabled: activeReportId === null,
      onClick: () => setActiveView("report"),
    },
    {
      key: "guidelines",
      title: "bob-regulations",
      onClick: () => {
        setSettingsTab("guidelines");
        setSettingsOpen(true);
      },
    },
    {
      key: "settings",
      title: "bob-settings",
      onClick: () => {
        setSettingsTab("template");
        setSettingsOpen(true);
      },
    },
  ];

  return (
    <div className="flex h-full w-12 flex-col items-center border-r border-brand-line bg-brand-surface-soft py-2">
      <div className="mb-3 grid h-9 w-9 place-items-center rounded-xl bg-brand-navy text-white shadow">
        <svg viewBox="0 0 24 24" className="h-5 w-5">
          <path
            fill="#F97316"
            d="M3 4h7v7H3V4zm0 9h7v7H3v-7zm9-9h9v4h-9V4zm0 6h9v10h-9V10z"
          />
        </svg>
      </div>
      {items.map((it) => (
        <button
          key={it.key}
          type="button"
          title={it.title}
          aria-label={it.title}
          aria-pressed={it.pressed}
          disabled={it.disabled}
          onClick={it.onClick}
          className={`mt-1 grid h-9 w-9 place-items-center rounded-lg transition ${
            it.active
              ? "bg-brand-blue-soft text-brand-blue"
              : "text-brand-subtle hover:bg-white hover:text-brand-ink"
          } ${it.disabled ? "cursor-not-allowed opacity-40" : ""}`}
        >
          <Icon k={it.key} />
        </button>
      ))}
    </div>
  );
}
