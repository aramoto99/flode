// ADR-0085 §4-A: 行を複数選べる表の primitive (SelectableTable)。

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SelectableTable, type SelectableTableRow } from "../src/components/ui/inspector";

afterEach(() => cleanup());

const ROWS: SelectableTableRow[] = [
  { key: "a", cells: ["alpha", 12, null] },
  { key: "b", cells: ["beta", 3.5, "x"] },
  { key: "c", cells: ["gamma", 0, "y"] },
];

/** 選択状態を持つ親 (実際の使い方と同じく、選択は呼ぶ側が持つ)。 */
function Harness({ disabled }: { disabled?: ReadonlySet<string> }): JSX.Element {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  return (
    <SelectableTable
      columns={["name", "n", "note"]}
      rows={ROWS}
      selected={selected}
      disabledKeys={disabled}
      disabledTitle="already there"
      onToggle={(k) =>
        setSelected((prev) => {
          const next = new Set(prev);
          if (next.has(k)) next.delete(k);
          else next.add(k);
          return next;
        })
      }
      testId="t"
    />
  );
}

function row(key: string): HTMLElement {
  return screen.getAllByTestId("t-row").find((r) => r.dataset.key === key)!;
}

describe("SelectableTable", () => {
  it("renders the headers as given without ARIA attributes invalid for a table", () => {
    render(<Harness />);
    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["name", "n", "note"]);
    // role=table では aria-multiselectable / aria-selected は無効 (選択はチェックボックスで伝える)
    expect(screen.getByRole("table").hasAttribute("aria-multiselectable")).toBe(false);
    for (const r of screen.getAllByTestId("t-row")) {
      expect(r.hasAttribute("aria-selected")).toBe(false);
      expect(r.hasAttribute("aria-disabled")).toBe(false);
    }
  });

  it("labels each checkbox with the row label, falling back to the key", () => {
    render(
      <SelectableTable
        columns={["name"]}
        rows={[
          { key: "raw‮key", cells: ["x"], label: "clean label" },
          { key: "plain", cells: ["y"] },
        ]}
        selected={new Set()}
        onToggle={() => undefined}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "clean label" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "plain" })).toBeTruthy();
  });

  it("toggles a row by clicking anywhere on it", () => {
    render(<Harness />);
    const box = within(row("b")).getByRole("checkbox") as HTMLInputElement;
    fireEvent.click(within(row("b")).getByText("beta"));
    expect(box.checked).toBe(true);
    expect(row("b").className).toContain("bg-blue-50");
    // フォーカスは行のチェックボックスに置く (キャンバスのショートカットを裏で効かせない)
    expect(document.activeElement).toBe(box);
    fireEvent.click(within(row("b")).getByText("beta"));
    expect(box.checked).toBe(false);
  });

  it("toggles once when the checkbox itself is clicked", () => {
    render(<Harness />);
    const box = within(row("a")).getByRole("checkbox") as HTMLInputElement;
    fireEvent.click(box);
    expect(box.checked).toBe(true);
    expect(row("a").dataset.selected).toBe("true");
  });

  it("does not select disabled rows and shows them dimmed", () => {
    const onToggle = vi.fn();
    render(
      <SelectableTable
        columns={["name"]}
        rows={[{ key: "a", cells: ["alpha"] }]}
        selected={new Set(["a"])}
        disabledKeys={new Set(["a"])}
        disabledTitle="already there"
        onToggle={onToggle}
        testId="t"
      />,
    );
    const r = row("a");
    fireEvent.click(within(r).getByText("alpha"));
    expect(onToggle).not.toHaveBeenCalled();
    const box = within(r).getByRole("checkbox") as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(box.checked).toBe(false);
    expect(r.dataset.disabled).toBe("true");
    expect(r.getAttribute("title")).toBe("already there");
    expect(r.className).toContain("text-slate-400");
  });

  it("right-aligns numbers and leaves null cells empty", () => {
    render(<Harness />);
    const cells = within(row("a")).getAllByRole("cell");
    // 先頭はチェックボックスの列
    expect(cells[2]!.dataset.cellKind).toBe("number");
    expect(cells[2]!.className).toContain("text-right");
    expect(cells[2]!.className).toContain("tabular-nums");
    expect(cells[2]!.textContent).toBe("12");
    expect(cells[3]!.dataset.cellKind).toBe("null");
    expect(cells[3]!.textContent).toBe("");
    expect(cells[1]!.getAttribute("title")).toBe("alpha");
  });

  it("shows the empty text when there are no rows", () => {
    render(
      <SelectableTable
        columns={[]}
        rows={[]}
        selected={new Set()}
        onToggle={() => undefined}
        testId="t"
        emptyText="nothing"
      />,
    );
    expect(screen.getByTestId("t-empty").textContent).toBe("nothing");
  });
});
