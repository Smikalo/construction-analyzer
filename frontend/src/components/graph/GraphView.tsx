"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { useChatStore } from "@/lib/store";
import type { GraphEdge, GraphNode } from "@/lib/mock";

const NODE_W = 168;
const NODE_H = 76;
const MIN_SCALE = 0.4;
const MAX_SCALE = 2.2;

function nodeCenter(n: GraphNode) {
  return { cx: n.x + NODE_W / 2, cy: n.y + NODE_H / 2 };
}

type DragState =
  | { kind: "none" }
  | { kind: "pan"; startX: number; startY: number; origX: number; origY: number }
  | {
      kind: "node";
      nodeId: string;
      startX: number;
      startY: number;
      origNX: number;
      origNY: number;
      moved: boolean;
    };

export function GraphView() {
  const nodes = useChatStore((s) => s.nodes);
  const edges = useChatStore((s) => s.edges);
  const files = useChatStore((s) => s.files);
  const warnings = useChatStore((s) => s.warnings);
  const activeFileId = useChatStore((s) => s.activeFileId);
  const setActiveFile = useChatStore((s) => s.setActiveFile);
  const setNodePosition = useChatStore((s) => s.setNodePosition);
  const chatHighlights = useChatStore((s) => s.chatHighlights);

  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const dragRef = useRef<DragState>({ kind: "none" });
  const containerRef = useRef<HTMLDivElement | null>(null);

  const warningByFile = useMemo(() => {
    const m = new Map<string, "critical" | "impacted">();
    for (const w of warnings) {
      const cur = m.get(w.fileId);
      if (cur === "critical") continue;
      m.set(w.fileId, w.severity);
    }
    return m;
  }, [warnings]);

  const fileById = useMemo(
    () => new Map(files.map((f) => [f.id, f])),
    [files],
  );

  const highlightNodeSet = new Set(chatHighlights.nodeIds);
  const highlightEdgeSet = new Set(chatHighlights.edgeIds);

  const onMouseDownBg = (e: React.MouseEvent) => {
    if ((e.target as Element).closest("[data-graph-node='1']")) return;
    dragRef.current = {
      kind: "pan",
      startX: e.clientX,
      startY: e.clientY,
      origX: pan.x,
      origY: pan.y,
    };
  };

  const onMouseDownNode = (n: GraphNode, e: React.MouseEvent) => {
    e.stopPropagation();
    dragRef.current = {
      kind: "node",
      nodeId: n.id,
      startX: e.clientX,
      startY: e.clientY,
      origNX: n.x,
      origNY: n.y,
      moved: false,
    };
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      if (d.kind === "pan") {
        const dx = e.clientX - d.startX;
        const dy = e.clientY - d.startY;
        setPan({ x: d.origX + dx, y: d.origY + dy });
      } else if (d.kind === "node") {
        const dx = (e.clientX - d.startX) / scale;
        const dy = (e.clientY - d.startY) / scale;
        if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
        setNodePosition(d.nodeId, d.origNX + dx, d.origNY + dy);
      }
    };
    const onUp = () => {
      const d = dragRef.current;
      if (d.kind === "node" && !d.moved) {
        const node = useChatStore
          .getState()
          .nodes.find((n) => n.id === d.nodeId);
        if (node) setActiveFile(node.fileId);
      }
      dragRef.current = { kind: "none" };
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [scale, setActiveFile, setNodePosition]);

  const onWheel = (e: React.WheelEvent) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
    setScale((s) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s * factor)));
  };

  const resetView = () => {
    setPan({ x: 0, y: 0 });
    setScale(1);
  };

  return (
    <div
      data-testid="graph-view"
      ref={containerRef}
      onMouseDown={onMouseDownBg}
      onWheel={onWheel}
      className="graph-bg relative h-[55%] min-h-[260px] flex-1 select-none overflow-hidden border-b border-brand-line bg-white"
      style={{
        cursor:
          dragRef.current.kind === "pan"
            ? "grabbing"
            : dragRef.current.kind === "node"
              ? "grabbing"
              : "grab",
      }}
    >
      <div className="pointer-events-none absolute left-0 right-0 top-0 z-10 flex items-center gap-3 border-b border-brand-line bg-white/85 px-4 py-2 backdrop-blur">
        <div className="text-[12px] font-semibold text-brand-navy">
          bob-graph · memory-palace
        </div>
        <span className="rounded-md bg-brand-blue-soft px-2 py-0.5 text-[10.5px] font-medium text-brand-blue">
          {nodes.length} bob-nodes · {edges.length} bob-edges
        </span>
        <div className="flex-1" />
        <Legend />
        <div className="pointer-events-auto ml-2 flex items-center gap-1 rounded-md border border-brand-line bg-white px-1 py-0.5">
          <button
            onClick={() =>
              setScale((s) => Math.max(MIN_SCALE, s / 1.15))
            }
            className="rounded px-1.5 text-[12px] text-brand-subtle hover:bg-brand-surface-soft hover:text-brand-ink"
            title="Zoom out"
          >
            −
          </button>
          <span className="text-[10.5px] tabular-nums text-brand-subtle">
            {Math.round(scale * 100)}%
          </span>
          <button
            onClick={() =>
              setScale((s) => Math.min(MAX_SCALE, s * 1.15))
            }
            className="rounded px-1.5 text-[12px] text-brand-subtle hover:bg-brand-surface-soft hover:text-brand-ink"
            title="Zoom in"
          >
            +
          </button>
          <span className="mx-1 h-4 w-px bg-brand-line" />
          <button
            onClick={resetView}
            className="rounded px-2 text-[10.5px] text-brand-subtle hover:bg-brand-surface-soft hover:text-brand-ink"
            title="Reset view"
          >
            Reset
          </button>
        </div>
      </div>

      <svg width="100%" height="100%" className="block">
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="#185FA5" />
          </marker>
          <marker
            id="arrow-highlight"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" fill="#F97316" />
          </marker>
        </defs>

        <g transform={`translate(${pan.x}, ${pan.y}) scale(${scale})`}>
          {edges.map((e: GraphEdge) => {
            const a = nodes.find((n) => n.id === e.source);
            const b = nodes.find((n) => n.id === e.target);
            if (!a || !b) return null;
            const { cx: x1, cy: y1 } = nodeCenter(a);
            const { cx: x2, cy: y2 } = nodeCenter(b);
            const isHL = highlightEdgeSet.has(e.id);
            return (
              <motion.line
                key={e.id}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={isHL ? "#F97316" : "#185FA5"}
                strokeOpacity={isHL ? 0.95 : 0.35}
                strokeWidth={isHL ? 2.4 : 1.4}
                strokeDasharray={isHL ? "0" : "4 4"}
                markerEnd={isHL ? "url(#arrow-highlight)" : "url(#arrow)"}
                initial={{ pathLength: 0, opacity: 0 }}
                animate={{ pathLength: 1, opacity: 1 }}
                transition={{ duration: 0.35 }}
              />
            );
          })}

          {nodes.map((n) => {
            const file = fileById.get(n.fileId);
            const sev = warningByFile.get(n.fileId);
            const isActive = activeFileId === n.fileId;
            const isHL = highlightNodeSet.has(n.id);

            const fill = "#FFFFFF";
            const stroke =
              sev === "critical"
                ? "#F97316"
                : sev === "impacted"
                  ? "#EAB308"
                  : isHL
                    ? "#185FA5"
                    : "#E3E8EF";
            const strokeWidth =
              sev === "critical"
                ? 2.4
                : sev === "impacted"
                  ? 2.0
                  : isHL
                    ? 2.0
                    : 1;

            return (
              <motion.g
                key={n.id}
                data-graph-node="1"
                onMouseDown={(e) => onMouseDownNode(n, e)}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3 }}
                style={{ cursor: "grab" }}
              >
                {sev === "critical" && (
                  <motion.circle
                    cx={n.x + NODE_W / 2}
                    cy={n.y + NODE_H / 2}
                    r={Math.max(NODE_W, NODE_H) / 1.6}
                    fill="#F97316"
                    fillOpacity={0.18}
                    animate={{ scale: [1, 1.04, 1] }}
                    transition={{
                      duration: 1.6,
                      repeat: Infinity,
                      ease: "easeInOut",
                    }}
                  />
                )}
                {isHL && (
                  <motion.rect
                    x={n.x - 6}
                    y={n.y - 6}
                    width={NODE_W + 12}
                    height={NODE_H + 12}
                    rx={14}
                    fill="none"
                    stroke="#185FA5"
                    strokeOpacity={0.5}
                    strokeWidth={2}
                    animate={{ opacity: [0.4, 0.9, 0.4] }}
                    transition={{
                      duration: 1.4,
                      repeat: Infinity,
                      ease: "easeInOut",
                    }}
                  />
                )}

                <rect
                  x={n.x}
                  y={n.y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={10}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={strokeWidth}
                  filter="drop-shadow(0 2px 6px rgba(14,42,71,0.06))"
                />
                <text
                  x={n.x + 14}
                  y={n.y + 22}
                  fontSize={11}
                  fontWeight={600}
                  fill="#0E2A47"
                >
                  {n.label.length > 22 ? n.label.slice(0, 22) + "…" : n.label}
                </text>
                <text x={n.x + 14} y={n.y + 40} fontSize={10} fill="#5C6B80">
                  {file?.kind?.toUpperCase() ?? "FILE"}
                  {file
                    ? ` · ${file.preview.split("\n")[0].slice(0, 22)}`
                    : ""}
                </text>
                {sev && (
                  <g>
                    <rect
                      x={n.x + NODE_W - 60}
                      y={n.y + 50}
                      width={50}
                      height={18}
                      rx={9}
                      fill={sev === "critical" ? "#FFE6CF" : "#FEF3C7"}
                      stroke={sev === "critical" ? "#F97316" : "#EAB308"}
                    />
                    <text
                      x={n.x + NODE_W - 35}
                      y={n.y + 62}
                      fontSize={9}
                      textAnchor="middle"
                      fill={sev === "critical" ? "#9A4910" : "#854D0E"}
                    >
                      {sev === "critical" ? "critical" : "impacted"}
                    </text>
                  </g>
                )}
                {isActive && (
                  <rect
                    x={n.x}
                    y={n.y + NODE_H - 3}
                    width={NODE_W}
                    height={3}
                    rx={1.5}
                    fill="#185FA5"
                  />
                )}
                {sev === "critical" && (
                  <rect
                    x={n.x}
                    y={n.y}
                    width={1}
                    height={1}
                    fill="transparent"
                    data-testid={`node-warning-critical-${n.id}`}
                  />
                )}
                {sev === "impacted" && (
                  <rect
                    x={n.x}
                    y={n.y}
                    width={1}
                    height={1}
                    fill="transparent"
                    data-testid={`node-warning-impacted-${n.id}`}
                  />
                )}
                {isHL && (
                  <rect
                    x={n.x}
                    y={n.y}
                    width={1}
                    height={1}
                    fill="transparent"
                    data-testid={`node-highlight-${n.id}`}
                  />
                )}
              </motion.g>
            );
          })}
        </g>
      </svg>

      <div className="pointer-events-none absolute bottom-2 left-3 rounded-md bg-white/85 px-2 py-1 text-[10.5px] text-brand-subtle backdrop-blur">
        Drag to pan · drag a bob-node to move it ·{" "}
        <kbd className="rounded border border-brand-line bg-white px-1 text-[9.5px]">
          ⌘
        </kbd>
        + scroll to zoom
      </div>

      {warnings.length > 0 && (
        <div className="pointer-events-none absolute right-4 top-14 max-w-xs rounded-xl border border-brand-orange-soft bg-white/95 p-3 brand-shadow">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-brand-orange">
            bob-hint
          </div>
          {warnings.slice(0, 2).map((w) => (
            <div key={w.id} className="mt-1 text-[12px] text-brand-ink">
              <span className="font-medium">{w.title}</span>
              <div className="text-[11px] text-brand-subtle">{w.hint}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="pointer-events-none flex items-center gap-3 text-[10.5px] text-brand-subtle">
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-brand-orange" /> critical
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-yellow-400" /> impacted
      </span>
      <span className="flex items-center gap-1">
        <span className="h-2 w-2 rounded-full bg-brand-blue" /> citation
      </span>
    </div>
  );
}
