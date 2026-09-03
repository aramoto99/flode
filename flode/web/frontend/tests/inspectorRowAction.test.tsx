// SPEC-0025 / ADR-0075 §論点 7: PropertyRow の labelControl / action slot と
// RowActionButton primitive。既存呼び出し (slot なし) の DOM 回帰も固定する。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PropertyRow,
  RowActionButton,
} from "../src/components/ui/inspector";

afterEach(() => cleanup());

describe("PropertyRow slots (SPEC-0025)", () => {
  it("slot なしの既存呼び出しは従来どおり静的 label を描く (回帰)", () => {
    render(
      <PropertyRow label="gain">
        <span data-testid="value">1.0</span>
      </PropertyRow>,
    );
    expect(screen.getByText("gain:")).toBeTruthy();
    expect(screen.getByTestId("value")).toBeTruthy();
  });

  it("labelControl 指定時は静的 label の代わりに control を label column に描く", () => {
    render(
      <PropertyRow
        label="gain"
        labelControl={<input data-testid="name-input" defaultValue="gain" />}
      >
        <span>1.0</span>
      </PropertyRow>,
    );
    expect(screen.getByTestId("name-input")).toBeTruthy();
    expect(screen.queryByText("gain:")).toBeNull();
  });

  it("action は行末に描かれる", () => {
    render(
      <PropertyRow label="gain" action={<button data-testid="act">del</button>}>
        <span>1.0</span>
      </PropertyRow>,
    );
    expect(screen.getByTestId("act")).toBeTruthy();
  });
});

describe("RowActionButton", () => {
  it("click で onClick が発火し、disabled では発火しない", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <RowActionButton onClick={onClick} testId="btn">
        削除
      </RowActionButton>,
    );
    fireEvent.click(screen.getByTestId("btn"));
    expect(onClick).toHaveBeenCalledTimes(1);
    rerender(
      <RowActionButton onClick={onClick} disabled testId="btn">
        削除
      </RowActionButton>,
    );
    fireEvent.click(screen.getByTestId("btn"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("tone=danger は枠と文字だけ rose (塗り潰さない)", () => {
    render(
      <RowActionButton tone="danger" testId="btn">
        削除
      </RowActionButton>,
    );
    const cls = screen.getByTestId("btn").className;
    expect(cls).toContain("text-rose-700");
    expect(cls).toContain("border-rose-400");
    expect(cls).toContain("bg-white");
    expect(cls).not.toContain("bg-rose-600");
  });
});
