import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Message } from "@/components/Message";

describe("<Message />", () => {
  it("renders user content", () => {
    render(
      <Message
        message={{ id: "1", role: "user", content: "hello world" }}
      />,
    );
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  it("renders assistant content via markdown", () => {
    render(
      <Message
        message={{
          id: "2",
          role: "assistant",
          content: "**bold** and `code`",
        }}
      />,
    );
    expect(screen.getByText("bold").tagName.toLowerCase()).toBe("strong");
    expect(screen.getByText("code").tagName.toLowerCase()).toBe("code");
  });

  it("shows the typing indicator while assistant is pending and empty", () => {
    render(
      <Message
        message={{
          id: "3",
          role: "assistant",
          content: "",
          pending: true,
        }}
      />,
    );
    expect(screen.getByLabelText("typing")).toBeInTheDocument();
  });

  it("uses different role labels for accessibility", () => {
    const { rerender } = render(
      <Message
        message={{ id: "1", role: "user", content: "hi" }}
      />,
    );
    expect(screen.getByRole("article")).toHaveAttribute("data-role", "user");
    rerender(
      <Message
        message={{ id: "1", role: "assistant", content: "ok" }}
      />,
    );
    expect(screen.getByRole("article")).toHaveAttribute(
      "data-role",
      "assistant",
    );
  });
});
