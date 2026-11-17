// ADR-0086 §6-A, SPEC-0037 受け入れ条件 4: 1 行を選ぶ表 (RowTable) と全幅の行 (PropertyStackRow)。
// - 単一選択 (クリック)、ダブルクリック / Enter で onActivate、↑ / ↓ で選択移動
// - error の行は赤字 + title に理由、dim の行は薄く
// - 0 件は emptyText、数値セルは右寄せ、null は空欄

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  PropertyStackRow,
  RowTable,
  type RowTableRow,
} from "../src/components/ui/inspector";

afterEach(() => cleanup());

const ROWS: RowTableRow[] = [
  { cells: ["a", 1, null] },
  { cells: ["b", 2, "x"], error: "unknown part: b" },
  { cells: ["c", null, null], dim: true },
];

/** 選択を持つ親。 */
function Harness({ onActivate }: { onActivate?: (i: number) => void }): JSX.Element {
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <RowTable
      columns={["name", "n", "note"]}
      rows={ROWS}
      selectedIndex={selected}
      onSelect={setSelected}
      onActivate={onActivate}
      testId="t"
      emptyText="none"
    />
  );
}

function rows(): HTMLElement[] {
  return screen.getAllByTestId("t-row");
}

describe("RowTable", () => {
  it("selects a single row on click", () => {
    render(<Harness />);
    fireEvent.click(rows()[0]!);
    expect(rows()[0]!.getAttribute("data-selected")).toBe("true");
    fireEvent.click(rows()[2]!);
    expect(rows()[0]!.hasAttribute("data-selected")).toBe(false);
    expect(rows()[2]!.getAttribute("data-selected")).toBe("true");
    expect(rows()[2]!.className).toContain("bg-blue-50");
  });

  it("activates on double click and on Enter", () => {
    const onActivate = vi.fn();
    render(<Harness onActivate={onActivate} />);
    fireEvent.doubleClick(rows()[1]!);
    expect(onActivate).toHaveBeenCalledWith(1);
    fireEvent.click(rows()[0]!);
    fireEvent.keyDown(screen.getByTestId("t"), { key: "Enter" });
    expect(onActivate).toHaveBeenLastCalledWith(0);
  });

  it("moves the selection with the arrow keys and stays in range", () => {
    render(<Harness />);
    const table = screen.getByTestId("t");
    fireEvent.keyDown(table, { key: "ArrowDown" });
    expect(rows()[0]!.getAttribute("data-selected")).toBe("true");
    fireEvent.keyDown(table, { key: "ArrowDown" });
    fireEvent.keyDown(table, { key: "ArrowDown" });
    fireEvent.keyDown(table, { key: "ArrowDown" });
    expect(rows()[2]!.getAttribute("data-selected")).toBe("true");
    fireEvent.keyDown(table, { key: "ArrowUp" });
    expect(rows()[1]!.getAttribute("data-selected")).toBe("true");
  });

  it("draws error rows red with the reason as tooltip, and dims pending rows", () => {
    render(<Harness />);
    const err = rows()[1]!;
    expect(err!.getAttribute("data-error")).toBe("true");
    expect(err!.getAttribute("title")).toBe("unknown part: b");
    expect(err.className).toContain("text-rose-700");
    expect(rows()[2]!.getAttribute("data-dim")).toBe("true");
    expect(rows()[2]!.className).toContain("text-slate-400");
    expect(rows()[0]!.hasAttribute("title")).toBe(false);
  });

  it("renders numbers right-aligned and null as blank", () => {
    render(<Harness />);
    const cells = rows()[0]!.querySelectorAll("td");
    expect(cells[1]!.getAttribute("data-cell-kind")).toBe("number");
    expect(cells[1]!.className).toContain("text-right");
    expect(cells[2]!.getAttribute("data-cell-kind")).toBe("null");
    expect(cells[2]!.textContent).toBe("");
  });

  it("shows emptyText without rows", () => {
    render(
      <RowTable
        columns={["a"]}
        rows={[]}
        selectedIndex={null}
        onSelect={() => undefined}
        testId="e"
        emptyText="No rows"
      />,
    );
    expect(screen.getByTestId("e-empty").textContent).toContain("No rows");
  });
});

describe("PropertyStackRow", () => {
  it("puts the label above full-width content", () => {
    render(
      <PropertyStackRow label="parts" testId="s">
        <div data-testid="content">x</div>
      </PropertyStackRow>,
    );
    expect(screen.getByTestId("s").textContent).toContain("parts:");
    expect(screen.getByTestId("content").textContent).toBe("x");
  });
});
