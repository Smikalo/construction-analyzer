import type {
  ChatChunk,
  Health,
  Readiness,
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
      handleFrame(frame, callbacks);
    }
  }

  if (buffer.trim()) handleFrame(buffer, callbacks);
  callbacks.onDone?.();
}

function handleFrame(frame: string, cb: StreamCallbacks): void {
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
  if (!dataRaw) return;

  if (event === "thread") {
    try {
      const obj = JSON.parse(dataRaw) as { thread_id?: string };
      if (obj.thread_id) cb.onThread?.(obj.thread_id);
    } catch {
      /* ignore */
    }
    return;
  }

  let chunk: ChatChunk | null = null;
  try {
    chunk = JSON.parse(dataRaw) as ChatChunk;
  } catch {
    return;
  }
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
      // onDone is called once the stream actually ends; ignore duplicate done
      // chunks emitted by the backend.
      break;
  }
}
