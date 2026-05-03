import type {
  ChatChunk,
  Health,
  JsonObject,
  Readiness,
  ReportCardPayload,
  ReportGatePayload,
  ReportSessionInspectionResponse,
  ReportSessionLaunchRequest,
  ReportSessionLaunchResponse,
  ThreadHistory,
  ThreadInfo,
} from "@/types";

const RAW_BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export const BACKEND_URL = RAW_BACKEND_URL.replace(/\/$/, "");

const url = (path: string): string =>
  path.startsWith("http") ? path : `${BACKEND_URL}${path}`;

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
}

export async function fetchHealth(): Promise<Health> {
  return jsonOrThrow<Health>(await fetch(url("/health")));
}

export async function fetchReadiness(): Promise<Readiness> {
  return jsonOrThrow<Readiness>(await fetch(url("/ready")));
}

export async function createThread(): Promise<string> {
  const body = await jsonOrThrow<{ thread_id: string }>(
    await fetch(url("/api/threads"), { method: "POST" }),
  );
  return body.thread_id;
}

export async function listThreads(): Promise<ThreadInfo[]> {
  return jsonOrThrow<ThreadInfo[]>(await fetch(url("/api/threads")));
}

export async function getHistory(threadId: string): Promise<ThreadHistory> {
  return jsonOrThrow<ThreadHistory>(
    await fetch(url(`/api/threads/${encodeURIComponent(threadId)}/history`)),
  );
}

export async function deleteThread(threadId: string): Promise<void> {
  const res = await fetch(
    url(`/api/threads/${encodeURIComponent(threadId)}`),
    { method: "DELETE" },
  );
  if (!res.ok && res.status !== 204) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function ingestFiles(files: File[]): Promise<{
  ingested_files: number;
  ingested_chunks: number;
  memory_ids: string[];
}> {
  const form = new FormData();
  for (const f of files) form.append("files", f, f.name);
  return jsonOrThrow(
    await fetch(url("/api/ingest"), { method: "POST", body: form }),
  );
}

export async function createOrResumeReportSession(
  req: ReportSessionLaunchRequest = {},
): Promise<ReportSessionLaunchResponse> {
  return jsonOrThrow<ReportSessionLaunchResponse>(
    await fetch(url("/api/reports"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}

export async function getReportSession(
  sessionId: string,
): Promise<ReportSessionInspectionResponse> {
  return jsonOrThrow<ReportSessionInspectionResponse>(
    await fetch(url(`/api/reports/${encodeURIComponent(sessionId)}`)),
  );
}

export async function answerReportGate(
  sessionId: string,
  gateId: string,
  answer: JsonObject,
): Promise<void> {
  const res = await fetch(
    url(
      `/api/reports/${encodeURIComponent(sessionId)}/gates/${encodeURIComponent(
        gateId,
      )}/answer`,
    ),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    },
  );
  await throwIfNotOk(res);
}

export type StreamCallbacks = {
  onToken?: (token: string) => void;
  onToolCall?: (name: string) => void;
  onToolResult?: (name: string) => void;
  onThread?: (threadId: string) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
};

export type ChatRequest = {
  message: string;
  thread_id?: string | null;
  signal?: AbortSignal;
};

export async function streamChat(
  req: ChatRequest,
  callbacks: StreamCallbacks,
): Promise<void> {
  const res = await fetch(url("/api/chat"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      message: req.message,
      thread_id: req.thread_id ?? null,
    }),
    signal: req.signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }

  await readSseFrames(res, (frame) => handleChatFrame(frame, callbacks));
  callbacks.onDone?.();
}

export type ReportStreamCallbacks = {
  onReportCard?: (card: ReportCardPayload) => void;
  onReportGate?: (gate: ReportGatePayload) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
  signal?: AbortSignal;
};

export async function streamReportSession(
  sessionId: string,
  callbacks: ReportStreamCallbacks,
): Promise<void> {
  const res = await fetch(
    url(`/api/reports/${encodeURIComponent(sessionId)}/stream`),
    {
      headers: { Accept: "text/event-stream" },
      signal: callbacks.signal,
    },
  );

  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  }

  await readSseFrames(res, (frame) => handleReportFrame(frame, callbacks));
  callbacks.onDone?.();
}

async function readSseFrames(
  res: Response,
  onFrame: (frame: string) => void,
): Promise<void> {
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      if (!frame.trim()) continue;
      onFrame(frame);
    }
  }

  if (buffer.trim()) onFrame(buffer);
}

function handleChatFrame(frame: string, cb: StreamCallbacks): void {
  const parsed = parseSseFrame(frame);
  if (!parsed) return;

  if (parsed.event === "thread") {
    try {
      const obj = JSON.parse(parsed.dataRaw) as { thread_id?: string };
      if (obj.thread_id) cb.onThread?.(obj.thread_id);
    } catch {
      /* ignore */
    }
    return;
  }

  const chunk = parseChunkFrame(frame);
  if (!chunk) return;

  switch (chunk.type) {
    case "token":
      if (chunk.data) cb.onToken?.(chunk.data);
      break;
    case "tool_call":
      cb.onToolCall?.(chunk.data);
      break;
    case "tool_result":
      cb.onToolResult?.(chunk.data);
      break;
    case "error":
      cb.onError?.(chunk.data);
      break;
    case "done":
    case "report_card":
    case "report_gate":
      // onDone is called once the stream actually ends; ignore duplicate done
      // chunks emitted by the backend. Report chunks are consumed by the report
      // stream client, not the normal chat stream client.
      break;
  }
}

function handleReportFrame(frame: string, cb: ReportStreamCallbacks): void {
  const chunk = parseChunkFrame(frame);
  if (!chunk) return;

  switch (chunk.type) {
    case "report_card":
      cb.onReportCard?.(chunk.payload);
      break;
    case "report_gate":
      cb.onReportGate?.(chunk.payload);
      break;
    case "error":
      cb.onError?.(chunk.data);
      break;
    case "done":
    case "token":
    case "tool_call":
    case "tool_result":
      break;
  }
}

function parseChunkFrame(frame: string): ChatChunk | null {
  const parsed = parseSseFrame(frame);
  if (!parsed || parsed.event !== "message") return null;

  try {
    return JSON.parse(parsed.dataRaw) as ChatChunk;
  } catch {
    return null;
  }
}

function parseSseFrame(
  frame: string,
): { event: string; dataRaw: string } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  const dataRaw = dataLines.join("\n");
  if (!dataRaw) return null;
  return { event, dataRaw };
}
