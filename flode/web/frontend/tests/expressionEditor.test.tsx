// SPEC-0011 §テスト戦略: ExpressionEditor primitive の単体テスト。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExpressionEditor } from "../src/components/ui/inspector";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string) => k,
  }),
}));

afterEach(() => cleanup());

describe("ExpressionEditor", () => {
  it("commits draft text on blur", () => {
    const onCommit = vi.fn();
    render(
      <ExpressionEditor
        value="u[0]"
        testid="expr"
        onCommit={onCommit}
      />,
    );
    const ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "u[0]**2 + sin(t)" } });
    fireEvent.blur(ta);
    expect(onCommit).toHaveBeenCalledWith("u[0]**2 + sin(t)");
  });

  it("supports multi-line input", () => {
    const onCommit = vi.fn();
    render(
      <ExpressionEditor
        value=""
        testid="expr"
        onCommit={onCommit}
      />,
    );
    const ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "u[0]\nu[1]" } });
    fireEvent.blur(ta);
    expect(onCommit).toHaveBeenCalledWith("u[0]\nu[1]");
  });

  it("rows expands with line count (min 2, max 8 cap)", () => {
    render(
      <ExpressionEditor
        value="u[0]"
        testid="expr"
        onCommit={vi.fn()}
      />,
    );
    let ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    // 1 行 → min cap 2
    expect(ta.rows).toBe(2);

    // 5 行入力 → 5 行 (cap 内)
    fireEvent.change(ta, { target: { value: "a\nb\nc\nd\ne" } });
    ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    expect(ta.rows).toBe(5);

    // 12 行入力 → max cap 8
    fireEvent.change(ta, {
      target: { value: "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n12" },
    });
    ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    expect(ta.rows).toBe(8);
  });

  it("syncs draft when value prop changes externally (model load)", () => {
    const onCommit = vi.fn();
    const { rerender } = render(
      <ExpressionEditor
        value="u[0]"
        testid="expr"
        onCommit={onCommit}
      />,
    );
    rerender(
      <ExpressionEditor
        value="sin(t)"
        testid="expr"
        onCommit={onCommit}
      />,
    );
    const ta = screen.getByTestId("expr") as HTMLTextAreaElement;
    expect(ta.value).toBe("sin(t)");
  });
});
