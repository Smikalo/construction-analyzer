export function TypingIndicator() {
  return (
    <span
      aria-label="typing"
      role="status"
      className="inline-flex items-center gap-1"
    >
      <span className="h-2 w-2 animate-pulse-soft rounded-full bg-brand-mute" />
      <span
        className="h-2 w-2 animate-pulse-soft rounded-full bg-brand-mute"
        style={{ animationDelay: "120ms" }}
      />
      <span
        className="h-2 w-2 animate-pulse-soft rounded-full bg-brand-mute"
        style={{ animationDelay: "240ms" }}
      />
    </span>
  );
}
