export type Role = "user" | "assistant" | "system" | "tool";

export type Message = {
  id: string;
  role: Role;
  content: string;
  pending?: boolean;
};

export type ChatChunk =
  | { type: "token"; data: string }
  | { type: "tool_call"; data: string }
  | { type: "tool_result"; data: string }
  | { type: "error"; data: string }
  | { type: "done"; data: string };

export type ThreadInfo = {
  thread_id: string;
  message_count: number;
  last_message_at: number | null;
};

export type ThreadHistory = {
  thread_id: string;
  messages: { role: Role; content: string }[];
};

export type Health = { status: "ok" };

export type Readiness = {
  status: "ready" | "degraded";
  ollama: boolean;
  postgres: boolean;
  checkpointer: boolean;
  kb: boolean;
  detail: string | null;
};
