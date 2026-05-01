import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Composer } from "@/components/Composer";

describe("<Composer />", () => {
  it("calls onSend with the typed text and clears the input", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);
    const user = userEvent.setup();

    const input = screen.getByPlaceholderText(/message/i);
    await user.type(input, "hello there");
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledWith("hello there");
    expect((input as HTMLTextAreaElement).value).toBe("");
  });

  it("submits on Enter without Shift", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);
    const user = userEvent.setup();

    const input = screen.getByPlaceholderText(/message/i);
    await user.type(input, "ping{enter}");

    expect(onSend).toHaveBeenCalledWith("ping");
  });

  it("does not submit when disabled", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={true} />);
    const user = userEvent.setup();

    const input = screen.getByPlaceholderText(/message/i);
    await user.type(input, "stuff");
    const btn = screen.getByRole("button", { name: /send/i });
    expect(btn).toBeDisabled();

    await user.click(btn);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not submit empty / whitespace-only messages", async () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} disabled={false} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();

    await user.type(screen.getByPlaceholderText(/message/i), "   {enter}");
    expect(onSend).not.toHaveBeenCalled();
  });
});
