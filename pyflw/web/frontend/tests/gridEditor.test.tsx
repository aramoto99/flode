// SPEC-0017 §テスト戦略: GridEditor primitive の単体テスト。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GridEditor } from "../src/components/ui/inspector";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts ? `${k}:${JSON.stringify(opts)}` : k,
  }),
}));

afterEach(() => cleanup());

describe("GridEditor", () => {
  it("renders a table with all cells", () => {
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("grid-cell-0-0")).toBeTruthy();
    expect(screen.getByTestId("grid-cell-0-1")).toBeTruthy();
    expect(screen.getByTestId("grid-cell-1-0")).toBeTruthy();
    expect(screen.getByTestId("grid-cell-1-1")).toBeTruthy();
  });

  it("commits cell edit on blur", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    const cell = screen.getByTestId("grid-cell-0-1") as HTMLInputElement;
    fireEvent.change(cell, { target: { value: "99" } });
    fireEvent.blur(cell);
    expect(onChange).toHaveBeenCalledWith([
      [0, 99],
      [20, 30],
    ]);
  });

  it("does not commit on empty cell input", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    const cell = screen.getByTestId("grid-cell-0-1") as HTMLInputElement;
    fireEvent.change(cell, { target: { value: "" } });
    fireEvent.blur(cell);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("adds a new row with zeros via [+ Row]", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-add-row"));
    expect(onChange).toHaveBeenCalledWith([
      [0, 10],
      [20, 30],
      [0, 0],
    ]);
  });

  it("adds a new column with zeros via [+ Col]", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-add-col"));
    expect(onChange).toHaveBeenCalledWith([
      [0, 10, 0],
      [20, 30, 0],
    ]);
  });

  it("removes a row via × button", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
          [40, 50],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-remove-row-1"));
    expect(onChange).toHaveBeenCalledWith([
      [0, 10],
      [40, 50],
    ]);
  });

  it("removes a column via × button", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[
          [0, 10, 20],
          [30, 40, 50],
        ]}
        testid="grid"
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByTestId("grid-remove-col-1"));
    expect(onChange).toHaveBeenCalledWith([
      [0, 20],
      [30, 50],
    ]);
  });

  it("blocks last-row removal", () => {
    const onChange = vi.fn();
    render(
      <GridEditor
        value={[[1, 2]]}
        testid="grid"
        onChange={onChange}
      />,
    );
    // 唯一の行は削除ボタンが表示されない (nRows <= 1)
    expect(screen.queryByTestId("grid-remove-row-0")).toBeNull();
  });

  it("shows shape mismatch warning when rowCountLink differs", () => {
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        rowCountLink={3}
        colCountLink={2}
        testid="grid"
        onChange={vi.fn()}
      />,
    );
    // shape_mismatch key が含まれる (mock t は key を返す)
    const shape = screen.getByTestId("grid-shape");
    expect(shape.textContent).toContain("inspector.grid.shape_mismatch");
  });

  it("shows large-table warning above threshold", () => {
    // 51 行で警告閾値超え
    const value = Array.from({ length: 51 }, () => [0, 1]);
    render(
      <GridEditor value={value} testid="grid" onChange={vi.fn()} />,
    );
    const warning = screen.getAllByRole("status")[0];
    expect(warning.textContent).toContain("inspector.grid.large_warning");
  });

  it("toggles to JSON mode and back", () => {
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        testid="grid"
        onChange={vi.fn()}
      />,
    );
    // grid mode: table 存在
    expect(screen.queryByTestId("grid-table")).toBeTruthy();
    // [JSON ▼] クリックで JsonArrayEditor mode
    fireEvent.click(screen.getByTestId("grid-to-json"));
    expect(screen.queryByTestId("grid-table")).toBeNull();
    expect(screen.queryByTestId("grid-json")).toBeTruthy();
    // back-to-grid
    fireEvent.click(screen.getByTestId("grid-back-to-grid"));
    expect(screen.queryByTestId("grid-table")).toBeTruthy();
  });

  it("disables cell edits and buttons in readOnly mode", () => {
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        readOnly
        testid="grid"
        onChange={vi.fn()}
      />,
    );
    const cell = screen.getByTestId("grid-cell-0-0") as HTMLInputElement;
    expect(cell.disabled).toBe(true);
    const addRow = screen.getByTestId("grid-add-row") as HTMLButtonElement;
    expect(addRow.disabled).toBe(true);
  });

  it("renders user-supplied row/col labels", () => {
    render(
      <GridEditor
        value={[
          [0, 10],
          [20, 30],
        ]}
        rowLabels={["rpm 1k", "rpm 3k"]}
        colLabels={["throttle 0", "throttle 1"]}
        testid="grid"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("rpm 1k")).toBeTruthy();
    expect(screen.getByText("throttle 0")).toBeTruthy();
  });
});
