import { create } from "zustand";
import type { Message, Role } from "@/types";
import {
  initialEdges,
  initialFiles,
  initialGuidelines,
  initialNodes,
  initialSnapshots,
  initialTemplate,
  mockChatReply,
  mockDropPayload,
  mockShouldWarn,
  type GraphEdge,
  type GraphNode,
  type Guideline,
  type ProjectFile,
  type Snapshot,
  type SnapshotReason,
  type TemplateSection,
  type Warning,
} from "@/lib/mock";

export const THREAD_STORAGE_KEY = "construction-analyzer.thread_id";

export type ConnectionStatus = "unknown" | "ready" | "degraded" | "offline";

export type OnboardingStep = "step1" | "step2" | "step3" | "ready";

type State = {
  messages: Message[];
  threadId: string | null;
  status: ConnectionStatus;

  // Onboarding
  onboardingStep: OnboardingStep;
  projectZipName: string | null;
  projectEmails: string[];
  conversationsZipName: string | null;
  loadingProgress: number;

  // Project / graph
  files: ProjectFile[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  activeFileId: string | null;
  warnings: Warning[];

  // Snapshots
  snapshots: Snapshot[];
  activeSnapshotId: string | null;

  // Chat highlights
  chatHighlights: { nodeIds: string[]; edgeIds: string[] };

  // Guidelines + template
  guidelines: Guideline[];
  template: TemplateSection[];

  // Panels
  profileOpen: boolean;
  settingsOpen: boolean;
  settingsTab: "guidelines" | "template";
};

type Actions = {
  // Original
  reset: () => void;
  setThreadId: (id: string | null) => void;
  hydrateThreadIdFromStorage: () => void;
  clearThread: () => void;
  appendUserMessage: (content: string) => string;
  startAssistantMessage: () => string;
  appendAssistantToken: (id: string, token: string) => void;
  finishAssistantMessage: (id: string) => void;
  errorOnAssistantMessage: (id: string, error: string) => void;
  hydrateMessagesFromHistory: (
    history: { role: Role; content: string }[],
  ) => void;
  setStatus: (s: ConnectionStatus) => void;

  // Onboarding
  setProjectZip: (name: string) => void;
  setProjectEmails: (emails: string[]) => void;
  setConversationsZip: (name: string) => void;
  advanceOnboarding: (next: OnboardingStep) => void;
  setLoadingProgress: (p: number) => void;

  // Files
  setActiveFile: (id: string | null) => void;
  dropFile: (name: string) => Snapshot;
  setNodePosition: (id: string, x: number, y: number) => void;

  // Snapshots
  selectSnapshot: (id: string) => void;
  triggerSnapshot: (
    reason: SnapshotReason,
    label: string,
    extraWarnings?: Warning[],
  ) => Snapshot;

  // Chat
  setChatHighlights: (nodeIds: string[]) => void;
  sendMockChat: (text: string) => void;

  // Guidelines / template
  addGuideline: (g: Guideline) => void;
  removeGuideline: (id: string) => void;
  editTemplateBody: (sectionId: string, body: string) => void;
  editTemplateComment: (
    sectionId: string,
    commentId: string,
    patch: Partial<{ citation: string; formula: string; note: string }>,
  ) => void;

  // Panels
  setProfileOpen: (open: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setSettingsTab: (tab: "guidelines" | "template") => void;
};

const INITIAL: State = {
  messages: [],
  threadId: null,
  status: "unknown",

  onboardingStep: "step1",
  projectZipName: null,
  projectEmails: [],
  conversationsZipName: null,
  loadingProgress: 0,

  files: initialFiles,
  nodes: initialNodes,
  edges: initialEdges,
  activeFileId: null,
  warnings: [],

  snapshots: initialSnapshots,
  activeSnapshotId: initialSnapshots[0].id,

  chatHighlights: { nodeIds: [], edgeIds: [] },

  guidelines: initialGuidelines,
  template: initialTemplate,

  profileOpen: false,
  settingsOpen: false,
  settingsTab: "guidelines",
};

const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

function findEdgeIdsBetween(edges: GraphEdge[], nodeIds: string[]): string[] {
  const set = new Set(nodeIds);
  return edges
    .filter((e) => set.has(e.source) && set.has(e.target))
    .map((e) => e.id);
}

export const useChatStore = create<State & Actions>((set, get) => ({
  ...INITIAL,

  reset: () => set({ ...INITIAL }),

  setThreadId: (id) => {
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(THREAD_STORAGE_KEY, id);
      else window.localStorage.removeItem(THREAD_STORAGE_KEY);
    }
    set({ threadId: id });
  },

  hydrateThreadIdFromStorage: () => {
    if (typeof window === "undefined") return;
    const id = window.localStorage.getItem(THREAD_STORAGE_KEY);
    set({ threadId: id });
  },

  clearThread: () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(THREAD_STORAGE_KEY);
    }
    set({ messages: [], threadId: null });
  },

  appendUserMessage: (content) => {
    const id = newId();
    set((s) => ({
      messages: [...s.messages, { id, role: "user", content }],
    }));
    return id;
  },

  startAssistantMessage: () => {
    const id = newId();
    set((s) => ({
      messages: [
        ...s.messages,
        { id, role: "assistant", content: "", pending: true },
      ],
    }));
    return id;
  },

  appendAssistantToken: (id, token) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + token } : m,
      ),
    }));
  },

  finishAssistantMessage: (id) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, pending: false } : m,
      ),
    }));
  },

  errorOnAssistantMessage: (id, error) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id
          ? { ...m, pending: false, content: m.content || `Error: ${error}` }
          : m,
      ),
    }));
  },

  hydrateMessagesFromHistory: (history) => {
    set({
      messages: history.map((h) => ({
        id: newId(),
        role: h.role,
        content: h.content,
      })),
    });
  },

  setStatus: (s) => set({ status: s }),

  // Onboarding -------------------------------------------------------------

  setProjectZip: (name) => set({ projectZipName: name }),
  setProjectEmails: (emails) => set({ projectEmails: emails }),
  setConversationsZip: (name) => set({ conversationsZipName: name }),
  advanceOnboarding: (next) => set({ onboardingStep: next }),
  setLoadingProgress: (p) => set({ loadingProgress: p }),

  // Files ------------------------------------------------------------------

  setActiveFile: (id) => set({ activeFileId: id }),

  setNodePosition: (id, x, y) =>
    set((s) => ({
      nodes: s.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)),
    })),

  dropFile: (name) => {
    const payload = mockDropPayload(name);
    set((s) => ({
      files: [...s.files, payload.newFile],
      nodes: [...s.nodes, payload.newNode],
      edges: [...s.edges, ...payload.newEdges],
      warnings: payload.warnings,
    }));
    return get().triggerSnapshot("upload", `bob-upload: ${name}`, payload.warnings);
  },

  // Snapshots --------------------------------------------------------------

  selectSnapshot: (id) => {
    const snap = get().snapshots.find((s) => s.id === id);
    if (!snap) return;
    set({
      activeSnapshotId: id,
      files: snap.files,
      nodes: snap.nodes,
      edges: snap.edges,
      warnings: snap.warnings,
    });
  },

  triggerSnapshot: (reason, label, extraWarnings) => {
    const state = get();
    const warnings: Warning[] = mockShouldWarn(reason)
      ? (extraWarnings ?? state.warnings)
      : [];
    const snap: Snapshot = {
      id: `snap_${newId()}`,
      reason,
      label,
      timestamp: new Date().toISOString().slice(0, 16).replace("T", " "),
      files: state.files,
      nodes: state.nodes,
      edges: state.edges,
      warnings,
    };
    set((s) => ({
      snapshots: [...s.snapshots, snap],
      activeSnapshotId: snap.id,
      warnings,
    }));
    return snap;
  },

  // Chat highlights --------------------------------------------------------

  setChatHighlights: (nodeIds) => {
    const edgeIds = findEdgeIdsBetween(get().edges, nodeIds);
    set({ chatHighlights: { nodeIds, edgeIds } });
  },

  sendMockChat: (text) => {
    const userId = get().appendUserMessage(text);
    void userId;
    const id = get().startAssistantMessage();
    get().appendAssistantToken(id, mockChatReply.text);
    get().finishAssistantMessage(id);
    get().setChatHighlights(mockChatReply.citations);
  },

  // Guidelines / template --------------------------------------------------

  addGuideline: (g) => set((s) => ({ guidelines: [...s.guidelines, g] })),

  removeGuideline: (id) =>
    set((s) => ({ guidelines: s.guidelines.filter((g) => g.id !== id) })),

  editTemplateBody: (sectionId, body) => {
    set((s) => ({
      template: s.template.map((sec) =>
        sec.id === sectionId
          ? { ...sec, body, rewrittenAt: Date.now() }
          : sec,
      ),
    }));
    get().triggerSnapshot("template", `bob-template: ${sectionId}`);
  },

  editTemplateComment: (sectionId, commentId, patch) => {
    set((s) => ({
      template: s.template.map((sec) =>
        sec.id === sectionId
          ? {
              ...sec,
              rewrittenAt: Date.now(),
              comments: sec.comments.map((c) =>
                c.id === commentId ? { ...c, ...patch } : c,
              ),
            }
          : sec,
      ),
    }));
    get().triggerSnapshot("template", `bob-comment: ${commentId}`);
  },

  // Panels -----------------------------------------------------------------

  setProfileOpen: (open) => set({ profileOpen: open }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setSettingsTab: (tab) => set({ settingsTab: tab }),
}));
