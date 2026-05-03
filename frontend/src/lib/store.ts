import { create } from "zustand";
import {
  answerReportGate,
  createOrResumeReportSession,
  getReportSession,
  streamReportSession,
} from "@/lib/api";
import type {
  JsonObject,
  Message,
  ReportArtifact,
  ReportCardPayload,
  ReportExport,
  ReportGatePayload,
  ReportSessionInspectionResponse,
  ReportSessionLaunchResponse,
  ReportSessionStatus,
  ReportStage,
  ReportValidationFinding,
  Role,
} from "@/types";
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
export const REPORT_STORAGE_KEY = "construction-analyzer.report_id";

export type ConnectionStatus = "unknown" | "ready" | "degraded" | "offline";

export type OnboardingStep = "step1" | "step2" | "step3" | "ready";

type State = {
  messages: Message[];
  threadId: string | null;
  activeReportId: string | null;
  activeView: "graph" | "report";
  reportStatus: ReportSessionStatus | null;
  reportCards: ReportCardPayload[];
  currentGate: ReportGatePayload | null;
  stages: ReportStage[];
  artifacts: ReportArtifact[];
  validationFindings: ReportValidationFinding[];
  exports: ReportExport[];
  reportError: string | null;
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
  setActiveView: (view: "graph" | "report") => void;
  hydrateThreadIdFromStorage: () => void;
  clearThread: () => void;
  launchReport: () => Promise<ReportSessionLaunchResponse>;
  submitReportGateAnswer: (answer: JsonObject) => Promise<void>;
  hydrateReportFromStorage: () => Promise<void>;
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
  activeReportId: null,
  activeView: "graph",
  reportStatus: null,
  reportCards: [] as ReportCardPayload[],
  currentGate: null,
  stages: [] as ReportStage[],
  artifacts: [] as ReportArtifact[],
  validationFindings: [] as ReportValidationFinding[],
  exports: [] as ReportExport[],
  reportError: null,
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

function readStoredReportId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REPORT_STORAGE_KEY);
}

function persistReportId(reportId: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(REPORT_STORAGE_KEY, reportId);
}

const MAX_REPORT_ERROR_LENGTH = 240;

function normalizeReportError(error: unknown): string {
  const message =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "Unknown report error";
  const normalized = message.replace(/\s+/g, " ").trim() || "Unknown report error";
  return normalized.length > MAX_REPORT_ERROR_LENGTH
    ? `${normalized.slice(0, MAX_REPORT_ERROR_LENGTH - 1)}…`
    : normalized;
}

function normalizeNullableReportError(error: string | null): string | null {
  return error ? normalizeReportError(error) : null;
}

function readTextField(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function formatReportLabel(name: string): string {
  const normalized = name.replace(/_/g, " ").trim();
  if (!normalized) return "Report";
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function asJsonObject(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function inspectionStages(snapshot: ReportSessionInspectionResponse): ReportStage[] {
  return Array.isArray(snapshot.stages) ? snapshot.stages : [];
}

function inspectionGates(snapshot: ReportSessionInspectionResponse): ReportGatePayload[] {
  return Array.isArray(snapshot.gates) ? snapshot.gates : [];
}

function inspectionArtifacts(snapshot: ReportSessionInspectionResponse): ReportArtifact[] {
  return Array.isArray(snapshot.artifacts) ? snapshot.artifacts : [];
}

function inspectionValidationFindings(
  snapshot: ReportSessionInspectionResponse,
): ReportValidationFinding[] {
  return Array.isArray(snapshot.validation_findings)
    ? snapshot.validation_findings
    : [];
}

function inspectionExports(snapshot: ReportSessionInspectionResponse): ReportExport[] {
  return Array.isArray(snapshot.exports) ? snapshot.exports : [];
}

function inspectionLogs(
  snapshot: ReportSessionInspectionResponse,
): ReportSessionInspectionResponse["recent_logs"] {
  return Array.isArray(snapshot.recent_logs) ? snapshot.recent_logs : [];
}

function buildReportCardsFromInspection(
  snapshot: ReportSessionInspectionResponse,
): ReportCardPayload[] {
  const stages = inspectionStages(snapshot);
  const stageById = new Map(stages.map((stage) => [stage.stage_id, stage]));
  const cards: ReportCardPayload[] = [];

  for (const log of inspectionLogs(snapshot)) {
    const payload = asJsonObject(log.payload);
    const stage = log.stage_id ? stageById.get(log.stage_id) ?? null : null;
    const stageName =
      readTextField(payload["stage_name"]) ??
      stage?.name ??
      snapshot.current_stage ??
      "unknown";
    const stageLabel = formatReportLabel(stageName);

    if (log.message === "Report pipeline failed") {
      cards.push({
        session_id: log.session_id,
        stage_id: log.stage_id ?? snapshot.session.session_id,
        stage_name: stageName,
        kind: "failure",
        message:
          readTextField(payload["error"]) ?? snapshot.session.last_error ?? log.message,
        created_at: log.created_at,
        payload,
      });
      continue;
    }

    if (log.message.endsWith("stage started")) {
      cards.push({
        session_id: log.session_id,
        stage_id: log.stage_id ?? snapshot.session.session_id,
        stage_name: stageName,
        kind: "stage_started",
        message: `${stageLabel} stage started`,
        created_at: log.created_at,
        payload,
      });
      continue;
    }

    if (log.message.endsWith("stage completed")) {
      cards.push({
        session_id: log.session_id,
        stage_id: log.stage_id ?? snapshot.session.session_id,
        stage_name: stageName,
        kind: "stage_completed",
        message: `${stageLabel} stage completed`,
        created_at: log.created_at,
        payload,
      });
      continue;
    }

    if (log.message.endsWith("gate closed")) {
      cards.push({
        session_id: log.session_id,
        stage_id: log.stage_id ?? snapshot.session.session_id,
        stage_name: stageName,
        kind: "gate_closed",
        message: log.message.replace(/^Report /, ""),
        created_at: log.created_at,
        payload,
      });
    }
  }

  if (
    snapshot.session.status === "failed" &&
    snapshot.session.last_error &&
    !cards.some((card) => card.kind === "failure")
  ) {
    cards.push({
      session_id: snapshot.session.session_id,
      stage_id: snapshot.current_stage ?? snapshot.session.session_id,
      stage_name: formatReportLabel(snapshot.current_stage ?? "unknown"),
      kind: "failure",
      message: normalizeReportError(snapshot.session.last_error),
      created_at: snapshot.session.updated_at ?? snapshot.session.created_at,
      payload: { error: normalizeReportError(snapshot.session.last_error) },
    });
  }

  return cards;
}

function reportCardKey(card: ReportCardPayload): string {
  return [card.session_id, card.stage_id, card.kind, card.created_at].join("::");
}

function reportCardTimestamp(card: ReportCardPayload): number {
  const time = new Date(card.created_at).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function mergeReportCards(
  existingCards: ReportCardPayload[],
  snapshotCards: ReportCardPayload[],
  sessionId: string,
): ReportCardPayload[] {
  const indexed = new Map<string, { card: ReportCardPayload; order: number }>();
  let order = 0;

  for (const card of snapshotCards) {
    indexed.set(reportCardKey(card), { card, order });
    order += 1;
  }

  for (const card of existingCards) {
    if (card.session_id !== sessionId) continue;
    const key = reportCardKey(card);
    if (!indexed.has(key)) {
      indexed.set(key, { card, order });
      order += 1;
    }
  }

  return Array.from(indexed.values())
    .sort((a, b) =>
      reportCardTimestamp(a.card) - reportCardTimestamp(b.card) || a.order - b.order,
    )
    .map((entry) => entry.card);
}

function buildReportStateFromInspection(
  snapshot: ReportSessionInspectionResponse,
  existingCards: ReportCardPayload[] = [],
): Pick<
  State,
  | "activeReportId"
  | "reportStatus"
  | "reportCards"
  | "currentGate"
  | "stages"
  | "artifacts"
  | "validationFindings"
  | "exports"
  | "reportError"
> {
  const snapshotCards = buildReportCardsFromInspection(snapshot);
  const sessionId = snapshot.session.session_id;

  return {
    activeReportId: sessionId,
    reportStatus: snapshot.session.status,
    reportCards: mergeReportCards(existingCards, snapshotCards, sessionId),
    currentGate: inspectionGates(snapshot).find((gate) => gate.status === "open") ?? null,
    stages: inspectionStages(snapshot),
    artifacts: inspectionArtifacts(snapshot),
    validationFindings: inspectionValidationFindings(snapshot),
    exports: inspectionExports(snapshot),
    reportError: normalizeNullableReportError(snapshot.session.last_error),
  };
}

function shouldRefreshAfterReportCard(card: ReportCardPayload): boolean {
  return ["stage_completed", "stage_failed", "gate_closed", "failure"].includes(
    card.kind,
  );
}

function findEdgeIdsBetween(edges: GraphEdge[], nodeIds: string[]): string[] {
  const set = new Set(nodeIds);
  return edges
    .filter((e) => set.has(e.source) && set.has(e.target))
    .map((e) => e.id);
}

export const useChatStore = create<State & Actions>((set, get) => {
  const applyReportInspectionSnapshot = (
    inspection: ReportSessionInspectionResponse,
  ): void => {
    const update = buildReportStateFromInspection(
      inspection,
      get().reportCards,
    );
    set(update);
    persistReportId(inspection.session.session_id);
  };

  const refreshReportInspection = async (
    sessionId: string,
  ): Promise<ReportSessionInspectionResponse | null> => {
    try {
      const inspection = await getReportSession(sessionId);
      applyReportInspectionSnapshot(inspection);
      return inspection;
    } catch (error) {
      set({ reportError: normalizeReportError(error) });
      return null;
    }
  };

  return {
    ...INITIAL,

  reset: () => set({ ...INITIAL }),

  setThreadId: (id) => {
    if (typeof window !== "undefined") {
      if (id) window.localStorage.setItem(THREAD_STORAGE_KEY, id);
      else window.localStorage.removeItem(THREAD_STORAGE_KEY);
    }
    set({ threadId: id });
  },

  setActiveView: (view) => set({ activeView: view }),

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

  launchReport: async () => {
    const stateBeforeLaunch = get();
    const storedReportId = stateBeforeLaunch.activeReportId ?? readStoredReportId();
    const shouldOpenReportView =
      stateBeforeLaunch.activeView === "graph" && stateBeforeLaunch.activeReportId === null;
    const launch = await createOrResumeReportSession(
      storedReportId ? { session_id: storedReportId } : {},
    );

    persistReportId(launch.session_id);
    const isNewSession = storedReportId !== launch.session_id;
    set({
      activeReportId: launch.session_id,
      reportStatus: launch.status,
      reportError: null,
      ...(shouldOpenReportView ? { activeView: "report" } : {}),
      ...(isNewSession
        ? {
            reportCards: [],
            currentGate: null,
            stages: [],
            artifacts: [],
            validationFindings: [],
            exports: [],
          }
        : {}),
    });

    void refreshReportInspection(launch.session_id);

    void streamReportSession(launch.session_id, {
      onReportCard: (card) => {
        set((state) => {
          const next: Partial<State> = {
            reportCards: [...state.reportCards, card],
          };
          if (card.kind === "gate_closed") {
            next.currentGate = null;
            next.reportStatus = "active";
          } else if (card.kind === "stage_started") {
            next.reportStatus = "active";
          } else if (card.kind === "stage_completed") {
            next.reportStatus = state.currentGate ? "blocked" : "active";
          } else if (card.kind === "stage_failed" || card.kind === "failure") {
            next.reportStatus = "failed";
            next.reportError = normalizeReportError(card.message);
          }
          return next;
        });
        if (shouldRefreshAfterReportCard(card)) {
          void refreshReportInspection(launch.session_id);
        }
      },
      onReportGate: (gate) => {
        set({ currentGate: gate, reportStatus: "blocked", reportError: null });
        void refreshReportInspection(launch.session_id);
      },
      onError: (message) => {
        set({ reportError: normalizeReportError(message), reportStatus: "failed" });
      },
      onDone: () => {
        void refreshReportInspection(launch.session_id);
      },
    }).catch((error) => {
      set({ reportError: normalizeReportError(error), reportStatus: "failed" });
    });

    return launch;
  },

  submitReportGateAnswer: async (answer) => {
    const activeReportId = get().activeReportId ?? readStoredReportId();
    const gate = get().currentGate;
    if (!activeReportId || !gate) {
      set({ reportError: "No active report gate to answer" });
      return;
    }

    set({ reportError: null });
    try {
      await answerReportGate(activeReportId, gate.gate_id, answer);
      set({ currentGate: null, reportError: null });
      await refreshReportInspection(activeReportId);
    } catch (error) {
      set({ currentGate: gate, reportError: normalizeReportError(error) });
      throw error;
    }
  },

  hydrateReportFromStorage: async () => {
    const storedReportId = readStoredReportId();
    if (!storedReportId) return;

    try {
      const inspection = await getReportSession(storedReportId);
      applyReportInspectionSnapshot(inspection);
      set({ activeView: "report" });
    } catch (error) {
      set({ reportError: normalizeReportError(error) });
      throw error;
    }
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
  };
});
