/**
 * Hardcoded mock data for the IDE-style construction analyzer shell.
 * Everything is generic "bob-*" placeholder content — no real norms,
 * no real engineering firms, no real formulas. Pure UI demo material.
 */

export type ProjectFile = {
  id: string;
  name: string;
  path: string;
  kind: "pdf" | "dwg" | "py" | "msg" | "doc" | "xls" | "img" | "txt";
  parentId: string | null;
  isFolder?: boolean;
  preview: string;
  warningRange?: { startLine: number; endLine: number; note: string } | null;
};

export type GraphNode = {
  id: string;
  fileId: string;
  label: string;
  x: number;
  y: number;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
};

export type WarningSeverity = "critical" | "impacted";

export type Warning = {
  id: string;
  fileId: string;
  severity: WarningSeverity;
  title: string;
  hint: string;
};

export type SnapshotReason =
  | "initial"
  | "upload"
  | "edit"
  | "email"
  | "template";

export type Snapshot = {
  id: string;
  reason: SnapshotReason;
  label: string;
  timestamp: string;
  files: ProjectFile[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  warnings: Warning[];
};

export type Guideline = {
  id: string;
  title: string;
  description: string;
};

export type TemplateComment = {
  id: string;
  citation: string;
  formula: string;
  note: string;
};

export type TemplateSection = {
  id: string;
  title: string;
  body: string;
  comments: TemplateComment[];
  rewrittenAt?: number;
};

/**
 * Decide whether a snapshot triggered by a given reason should add new
 * warnings. Per the spec, warnings should NOT show on every snapshot —
 * only when the AI thinks the change critically impacts other files.
 * For the mock, only "upload" of certain files triggers warnings.
 */
export function mockShouldWarn(reason: SnapshotReason): boolean {
  return reason === "upload";
}

const ROOT_ID = "bob-project";

export const initialFiles: ProjectFile[] = [
  {
    id: ROOT_ID,
    name: "bob-project",
    path: "bob-project",
    kind: "doc",
    parentId: null,
    isFolder: true,
    preview: "",
  },
  {
    id: "bob_blueprint",
    name: "bob-blueprint.pdf",
    path: "bob-project/bob-blueprint.pdf",
    kind: "pdf",
    parentId: ROOT_ID,
    preview: [
      "BOB-BLUEPRINT — bob-project overview",
      "Owner: bob-client",
      "Phase: bob-phase 3 (design)",
      "",
      "1. bob-structure",
      "   - bob-frame, bob-span 7.2 bob-units",
      "   - bob-slab thickness 22 bob-units",
      "   - bob-column type B260",
      "",
      "2. bob-loads",
      "   - bob-self-load",
      "   - bob-use-load = 3 bob-units",
      "   - bob-snow-load = 0.7 bob-units",
      "",
      "3. bob-checks to perform",
      "   - bob-strength check",
      "   - bob-serviceability check",
      "   - bob-fire check (level 90)",
    ].join("\n"),
  },
  {
    id: "bob_floorplan",
    name: "bob-floorplan.dwg",
    path: "bob-project/bob-floorplan.dwg",
    kind: "dwg",
    parentId: ROOT_ID,
    preview: [
      "[bob-floorplan — DWG preview]",
      "",
      "  bob-axes A–F, 1–6",
      "  bob-grid 7.2 × 6.4 bob-units",
      "  bob-staircase: central (axis C/3–4)",
      "  bob-core: bob-concrete C30",
      "",
      "  bob-clear-height: 3.10 bob-units",
      "  bob-parapet: 0.90 bob-units",
    ].join("\n"),
  },
  {
    id: "bob_section",
    name: "bob-section.pdf",
    path: "bob-project/bob-section.pdf",
    kind: "pdf",
    parentId: ROOT_ID,
    preview: [
      "BOB-SECTION A-A",
      "",
      "bob-ground   ±0.00",
      "bob-floor 0  +0.32",
      "bob-floor 1  +3.42",
      "bob-floor 2  +6.52",
      "bob-floor 3  +9.62",
      "bob-roof    +12.80",
      "",
      "bob-base / bob-wall joint:",
      "  bob-waterproof concrete C30, 30 bob-units thick",
    ].join("\n"),
  },
  {
    id: "bob_foundation",
    name: "bob-foundation.py",
    path: "bob-project/bob-foundation.py",
    kind: "py",
    parentId: ROOT_ID,
    preview: [
      "# bob-foundation sizing (bob-rules)",
      "from math import sqrt",
      "",
      "def bob_size(N: float, bob_pressure: float = 0.30):",
      "    A_required = N / bob_pressure",
      "    side = sqrt(A_required)",
      "    return round(side, 2)",
      "",
      "# example: bob-column C/3, N = 1.85 bob-units",
      "if __name__ == \"__main__\":",
      "    print(bob_size(1.85))   # -> 2.48 bob-units",
    ].join("\n"),
  },
  {
    id: "bob_beam",
    name: "bob-beam.py",
    path: "bob-project/bob-beam.py",
    kind: "py",
    parentId: ROOT_ID,
    preview: [
      "# bob-beam check (bob-rules)",
      "from dataclasses import dataclass",
      "",
      "@dataclass",
      "class BobProfile:",
      "    A: float    # bob-units²",
      "    W_pl: float  # bob-units³",
      "",
      "BOB_BEAM_260 = BobProfile(A=86.8, W_pl=920)",
      "bob_yield = 23.5  # bob-strength",
      "",
      "def bob_moment(p: BobProfile) -> float:",
      "    return p.W_pl * bob_yield / 100  # bob-moment",
    ].join("\n"),
  },
  {
    id: "bob_comms",
    name: "bob-comms",
    path: "bob-project/bob-comms",
    kind: "doc",
    parentId: ROOT_ID,
    isFolder: true,
    preview: "",
  },
  {
    id: "bob_email_change",
    name: "bob-message-change.msg",
    path: "bob-project/bob-comms/bob-message-change.msg",
    kind: "msg",
    parentId: "bob_comms",
    preview: [
      "From: bob-client <client@bobworks.io>",
      "To:   team@bobworks.io",
      "Date: bob-day 18",
      "Subject: bob-change request for bob-slab",
      "",
      "Please bump bob-slab thickness from 22 to 24 bob-units,",
      "based on bob-tenant acoustics request.",
      "",
      "Cheers, bob-client",
    ].join("\n"),
  },
];

export const initialNodes: GraphNode[] = [
  { id: "n_blueprint", fileId: "bob_blueprint", label: "bob-blueprint", x: 110, y: 90 },
  { id: "n_floorplan", fileId: "bob_floorplan", label: "bob-floorplan", x: 360, y: 60 },
  { id: "n_section", fileId: "bob_section", label: "bob-section", x: 600, y: 100 },
  { id: "n_foundation", fileId: "bob_foundation", label: "bob-foundation.py", x: 200, y: 280 },
  { id: "n_beam", fileId: "bob_beam", label: "bob-beam.py", x: 470, y: 280 },
  { id: "n_email", fileId: "bob_email_change", label: "bob-message · day 18", x: 720, y: 280 },
];

export const initialEdges: GraphEdge[] = [
  { id: "e1", source: "n_blueprint", target: "n_floorplan" },
  { id: "e2", source: "n_floorplan", target: "n_section" },
  { id: "e3", source: "n_floorplan", target: "n_foundation" },
  { id: "e4", source: "n_floorplan", target: "n_beam" },
  { id: "e5", source: "n_email", target: "n_section" },
  { id: "e6", source: "n_blueprint", target: "n_foundation" },
];

export const initialSnapshots: Snapshot[] = [
  {
    id: "snap_init",
    reason: "initial",
    label: "bob-project initialised",
    timestamp: "bob-day 1 · 10:14",
    files: initialFiles,
    nodes: initialNodes,
    edges: initialEdges,
    warnings: [],
  },
];

export const initialGuidelines: Guideline[] = [
  { id: "bob_reg_1", title: "bob-regulation 001", description: "bob-basics for bob-structures" },
  { id: "bob_reg_2", title: "bob-regulation 002", description: "bob-actions on bob-structures" },
  { id: "bob_reg_3", title: "bob-regulation 003", description: "bob-design of bob-concrete works" },
  { id: "bob_reg_4", title: "bob-regulation 004", description: "bob-design of bob-steel works" },
  { id: "bob_handbook", title: "bob-handbook", description: "bob-fees and bob-services manual" },
];

export const initialTemplate: TemplateSection[] = [
  {
    id: "tpl_basics",
    title: "1. bob-basics",
    body: "bob-report for the bob-project. The bob-structure is a bob-frame with a bob-core, designed per bob-regulation 001 and bob-regulation 003.",
    comments: [
      {
        id: "c_basics_1",
        citation: "bob-regulation 001 §6.4",
        formula: "bob-design = γ_g · G + γ_q · Q + Σ ψ · γ · Q_i",
        note: "bob-load combination for bob-strength check.",
      },
    ],
  },
  {
    id: "tpl_loads",
    title: "2. bob-loads",
    body: "bob-self-load per bob-regulation 002, bob-use-load 3 bob-units (bob-office), bob-snow 0.7 bob-units, bob-wind 0.4 bob-units.",
    comments: [
      {
        id: "c_loads_1",
        citation: "bob-regulation 002 Table 6.2",
        formula: "bob-use-load = 3 bob-units",
        note: "bob-category B1 — bob-office floor.",
      },
    ],
  },
  {
    id: "tpl_slab",
    title: "3. bob-slab design",
    body: "bob-concrete slab C30, bob-rebar B500, bob-thickness 22 bob-units, bob-span 7.2 bob-units. Checked per bob-regulation 003.",
    comments: [
      {
        id: "c_slab_1",
        citation: "bob-regulation 003 §9.3",
        formula: "bob-min-rebar = 0.26 · (f_ct/f_y) · b · d",
        note: "bob-minimum rebar for bob-slabs.",
      },
      {
        id: "c_slab_2",
        citation: "bob-regulation 003 §7.4",
        formula: "bob-crack-width ≤ 0.3 bob-units",
        note: "bob-crack check at bob-serviceability.",
      },
    ],
  },
];

export const teamEmailSuggestions: string[] = [
  "alice@bobworks.io",
  "lena@bobworks.io",
  "tobias@bobworks.io",
];

/**
 * Hardcoded "AI" reply emitted by the chat panel. The bracketed
 * `[node:...]` markers are stripped from the visible text and used
 * to set chat highlights on the graph.
 */
export const mockChatReply = {
  text: "The bob-foundation [node:n_foundation] is directly tied to the bob-floorplan [node:n_floorplan] and the bob-loads pulled from the bob-blueprint [node:n_blueprint]. The bob-column at axis C/3 carries N ≈ 1.85 bob-units.",
  citations: ["n_foundation", "n_floorplan", "n_blueprint"],
};

/**
 * Build the warnings + dropped-in file used when the user drops a new
 * file into the file tree (e.g. a new bob-survey).
 */
export function mockDropPayload(droppedName: string) {
  const newFile: ProjectFile = {
    id: `dropped_${Date.now()}`,
    name: droppedName,
    path: `bob-project/${droppedName}`,
    kind: droppedName.toLowerCase().endsWith(".pdf") ? "pdf" : "doc",
    parentId: ROOT_ID,
    preview: [
      `=== ${droppedName} ===`,
      "",
      "bob-survey — bob-soil class C",
      "bob-bearing soil: bob-silty-gravel",
      "bob-allowed pressure: bob-pressure = 0.22 bob-units",
      "  ! lower than the previous bob-pressure 0.30 bob-units",
      "",
      "bob-water table: -2.40 bob-units below bob-ground",
      "  → bob-waterproof construction needed",
    ].join("\n"),
    warningRange: {
      startLine: 4,
      endLine: 6,
      note: "bob-pressure 0.22 < 0.30 bob-units — bob-foundation must be re-sized.",
    },
  };

  const newNode: GraphNode = {
    id: `node_${newFile.id}`,
    fileId: newFile.id,
    label: droppedName.replace(/\.[^.]+$/, ""),
    x: 880,
    y: 90,
  };

  const newEdges: GraphEdge[] = [
    { id: `edge_${newFile.id}_fund`, source: newNode.id, target: "n_foundation" },
    { id: `edge_${newFile.id}_blue`, source: newNode.id, target: "n_blueprint" },
  ];

  const warnings: Warning[] = [
    {
      id: `w_${newFile.id}_self`,
      fileId: newFile.id,
      severity: "critical",
      title: "bob-pressure mismatch",
      hint: "0.22 bob-units instead of 0.30 — critical for bob-foundation sizing.",
    },
    {
      id: `w_${newFile.id}_fund`,
      fileId: "bob_foundation",
      severity: "impacted",
      title: "bob-foundation.py — adjust bob-pressure",
      hint: "Default 0.30 → 0.22 bob-units, bob-area grows ~36 %.",
    },
    {
      id: `w_${newFile.id}_blue`,
      fileId: "bob_blueprint",
      severity: "impacted",
      title: "bob-blueprint — document bob-pressure",
      hint: "Add bob-pressure assumption, otherwise bob-claim risk.",
    },
  ];

  return { newFile, newNode, newEdges, warnings };
}
