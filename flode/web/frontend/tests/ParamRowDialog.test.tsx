// ADR-0086 §6-C, SPEC-0037 U-6〜U-9 / 受け入れ条件 6: 行の編集ダイアログ。
// - form → 種類・フィールド (text / choice / pick) → 入力 → compose → describe([row]) のプレビュー
// - OK は compose が成功し、プレビューの行に error が無いときだけ有効
//   (compose の例外・describe の行の error で無効、describe そのものの失敗は警告だけで有効)
// - 種類の切り替えでフィールドを既定値で埋める
// - pick の選択は検索結果が変わっても消えない
// - 編集: form に今の行、compose に index を送る

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import type { ParamRowsFormResponse, ParamRowsRequest } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: Record<string, unknown>) =>
      opts !== undefined ? `${k}:${JSON.stringify(opts)}` : k,
  }),
}));

const rowsMock = vi.fn<(req: ParamRowsRequest, signal?: AbortSignal) => Promise<unknown>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    paramRows: (req: ParamRowsRequest, signal?: AbortSignal) => rowsMock(req, signal),
  };
});

import { ParamRowDialog } from "../src/components/ParamRowDialog";
import { paramRowsQueue } from "../src/lib/paramRowsQueue";

const PARTS = ["bolt", "nut", "washer", "bolt_long"];

const FORM: ParamRowsFormResponse = {
  variants: [
    {
      id: "group",
      label: "Group",
      fields: [
        { key: "name", label: "Name", kind: "text" },
        {
          key: "mode",
          label: "Mode",
          kind: "choice",
          options: [
            { value: "sum", label: "Sum" },
            { value: "max", label: "Max" },
          ],
        },
        { key: "parts", label: "Parts", kind: "pick" },
      ],
    },
    { id: "raw", label: "Write directly", fields: [{ key: "text", label: "Row", kind: "text" }] },
  ],
  variant: "group",
  values: { name: "g", mode: "sum", parts: [] },
};

/** 部品ビン風の行エディタ。``err`` で始まる行は describe の行の error、名前 ``bad`` は compose の例外。 */
function fakeBlock(req: ParamRowsRequest): unknown {
  switch (req.action) {
    case "form": {
      const r = req as ParamRowsRequest<"form">;
      if (r.row === null) return FORM;
      return { ...FORM, variant: "raw", values: { text: r.row } };
    }
    case "compose": {
      const r = req as ParamRowsRequest<"compose">;
      if (r.variant === "raw") return { row: String(r.values.text ?? "") };
      if (r.values.name === "bad") {
        throw new ApiError(400, "400 name 'bad' is reserved", null, "name 'bad' is reserved");
      }
      const parts = (r.values.parts as string[]).join("|");
      return { row: `${String(r.values.name)}@${String(r.values.mode)}: part=${parts}` };
    }
    case "describe": {
      const r = req as ParamRowsRequest<"describe">;
      return {
        columns: ["name", "parts"],
        rows: r.rows.map((row) => ({
          cells: [row.split(/[@:]/)[0] ?? "", row.split("|").length],
          error: row.startsWith("err") ? "no such part" : null,
        })),
        ports: "input",
      };
    }
    case "search": {
      const r = req as ParamRowsRequest<"search">;
      const hits = PARTS.filter((p) => p.includes(r.query));
      return { columns: ["part"], rows: hits.map((p) => ({ cells: [p], value: p })), truncated: false };
    }
  }
  return null;
}

function openDialog(
  opts: { index?: number | null; rows?: string[] } = {},
): { onOk: ReturnType<typeof vi.fn>; onClose: ReturnType<typeof vi.fn> } {
  const onOk = vi.fn();
  const onClose = vi.fn();
  const rows = opts.rows ?? ["a@sum: part=bolt"];
  render(
    <ParamRowDialog
      typePath="flode_ws.parts.Bin"
      param="parts"
      index={opts.index ?? null}
      readRows={() => rows}
      readParams={() => ({ gain: 2 })}
      onOk={onOk}
      onClose={onClose}
    />,
  );
  return { onOk, onClose };
}

function okButton(): HTMLButtonElement {
  return screen.getByTestId("param-row-dialog-ok") as HTMLButtonElement;
}

function calls(action: string): ParamRowsRequest[] {
  return rowsMock.mock.calls.map((c) => c[0]).filter((r) => r.action === action);
}

beforeEach(() => {
  rowsMock.mockReset();
  rowsMock.mockImplementation(async (req) => fakeBlock(req));
});
afterEach(() => {
  cleanup();
  paramRowsQueue.reset();
});

describe("ParamRowDialog", () => {
  it("builds the form, previews the composed row and enables OK", async () => {
    const { onOk } = openDialog();
    await screen.findByTestId("param-row-field-name");
    expect(calls("form")[0]).toMatchObject({ row: null, params: { gain: 2 }, param: "parts" });
    // 種類が 2 つなので select が出る
    expect(screen.getByTestId("param-row-dialog-variant")).toBeTruthy();
    expect(okButton().disabled).toBe(true);

    fireEvent.change(screen.getByTestId("param-row-field-name"), { target: { value: "front" } });
    fireEvent.change(screen.getByTestId("param-row-field-mode"), { target: { value: "max" } });
    await waitFor(() =>
      expect(screen.getByTestId("param-row-preview-row").textContent).toBe("front@max: part="),
    );
    await waitFor(() => expect(okButton().disabled).toBe(false));
    const compose = calls("compose").at(-1) as ParamRowsRequest<"compose">;
    expect(compose).toMatchObject({
      variant: "group",
      values: { name: "front", mode: "max", parts: [] },
      rows: ["a@sum: part=bolt"],
      index: null,
    });
    expect(calls("describe").at(-1)).toMatchObject({ rows: ["front@max: part="] });
    expect(screen.getByTestId("param-row-preview-table").textContent).toContain("front");

    fireEvent.click(okButton());
    expect(onOk).toHaveBeenCalledWith("front@max: part=");
  });

  it("disables OK while a compose error is shown", async () => {
    openDialog();
    const name = await screen.findByTestId("param-row-field-name");
    fireEvent.change(name, { target: { value: "bad" } });
    const err = await screen.findByTestId("param-row-preview-error");
    expect(err.textContent).toContain("name 'bad' is reserved");
    expect(okButton().disabled).toBe(true);
  });

  it("disables OK when the previewed row has an error", async () => {
    openDialog();
    const name = await screen.findByTestId("param-row-field-name");
    fireEvent.change(name, { target: { value: "err" } });
    const err = await screen.findByTestId("param-row-preview-row-error");
    expect(err.textContent).toContain("no such part");
    expect(okButton().disabled).toBe(true);
  });

  it("keeps OK enabled with a warning when the preview describe itself fails", async () => {
    rowsMock.mockImplementation(async (req) => {
      if (req.action === "describe") throw new ApiError(400, "400 boom", null, "boom");
      return fakeBlock(req);
    });
    openDialog();
    await screen.findByTestId("param-row-field-name");
    await screen.findByTestId("param-row-preview-describe-warning");
    expect(okButton().disabled).toBe(false);
  });

  it("shows a form error and keeps OK disabled", async () => {
    rowsMock.mockImplementation(async (req) => {
      if (req.action === "form") throw new ApiError(400, "400 broken", null, "broken form");
      return fakeBlock(req);
    });
    openDialog();
    const err = await screen.findByTestId("param-row-dialog-form-error");
    expect(err.textContent).toContain("broken form");
    expect(okButton().disabled).toBe(true);
  });

  it("switching the variant fills its fields with defaults", async () => {
    openDialog();
    await screen.findByTestId("param-row-field-name");
    fireEvent.change(screen.getByTestId("param-row-dialog-variant"), { target: { value: "raw" } });
    const text = (await screen.findByTestId("param-row-field-text")) as HTMLInputElement;
    expect(text.value).toBe("");
    fireEvent.change(text, { target: { value: "x: part=nut" } });
    await waitFor(() =>
      expect(calls("compose").at(-1)).toMatchObject({ variant: "raw", values: { text: "x: part=nut" } }),
    );
  });

  it("edit sends the current row to form and the index to compose", async () => {
    openDialog({ index: 1, rows: ["a@sum: part=bolt", "b: part=nut"] });
    const text = (await screen.findByTestId("param-row-field-text")) as HTMLInputElement;
    expect(calls("form")[0]).toMatchObject({ row: "b: part=nut" });
    expect(text.value).toBe("b: part=nut");
    await waitFor(() =>
      expect(calls("compose").at(-1)).toMatchObject({ index: 1, variant: "raw" }),
    );
  });

  it("pick keeps the chosen values when the results change", async () => {
    openDialog();
    await screen.findByTestId("param-row-field-name");
    fireEvent.change(screen.getByTestId("param-row-pick-parts-query"), { target: { value: "bolt" } });
    await waitFor(() => expect(screen.getAllByTestId("param-row-pick-parts-table-row")).toHaveLength(2));
    expect(calls("search").at(-1)).toMatchObject({ field: "parts", query: "bolt", params: { gain: 2 } });
    fireEvent.click(screen.getAllByTestId("param-row-pick-parts-table-row")[0]!);
    fireEvent.change(screen.getByTestId("param-row-pick-parts-query"), { target: { value: "nut" } });
    await waitFor(() => expect(screen.getAllByTestId("param-row-pick-parts-table-row")).toHaveLength(1));
    fireEvent.click(screen.getAllByTestId("param-row-pick-parts-table-row")[0]!);
    const chosen = screen.getByTestId("param-row-pick-parts-selected");
    expect(chosen.textContent).toContain("bolt");
    expect(chosen.textContent).toContain("nut");
    await waitFor(() =>
      expect(calls("compose").at(-1)).toMatchObject({ values: { parts: ["bolt", "nut"] } }),
    );
    // 外す
    const remove = chosen.querySelector("button");
    act(() => {
      remove!.click();
    });
    expect(screen.getByTestId("param-row-pick-parts-selected").textContent).not.toContain("bolt");
  });

  it("cancels its queued requests when closed", async () => {
    let release: (() => void) | null = null;
    rowsMock.mockImplementation(
      (req, signal) =>
        new Promise((resolve, reject) => {
          release = () => resolve(fakeBlock(req));
          signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
        }),
    );
    openDialog();
    await waitFor(() => expect(calls("form")).toHaveLength(1));
    const signal = rowsMock.mock.calls[0]![1]!;
    cleanup();
    expect(signal.aborted).toBe(true);
    expect(paramRowsQueue.runningSlot).toBeNull();
    expect(release).not.toBeNull();
  });
});
