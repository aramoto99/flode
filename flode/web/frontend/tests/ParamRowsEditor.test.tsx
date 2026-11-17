// ADR-0086 §6-B / §5-D, SPEC-0037 U-1〜U-5 / U-11 / U-12 / P-1〜P-8 / 受け入れ条件 7・8:
// Inspector の行エディタ (表 + ボタン列)。
// - row_editor の引数は表で描き「探す…」を出さない。宣言のない引数は従来の JSON 欄のまま
// - describe の説明を表に出す。失敗時は表の上にエラー、各行は生の文字列
// - 途中の行の削除・↑ で配線が行に付いていく。1 操作 = 1 Undo
// - テキスト編集・describe の失敗中は番号で対応
// - ポートの応答待ちの間は操作ボタンが無効

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import type {
  BlockMetadata,
  FlwModel,
  ParamRowsRequest,
  ResolvedPortShapes,
} from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, opts?: string | Record<string, unknown>) =>
      typeof opts === "string"
        ? opts
        : opts !== undefined
          ? `${k}:${JSON.stringify(opts)}`
          : k,
  }),
}));

const TYPE = "flode_ws.parts.Bin";

const META: BlockMetadata = {
  type_path: TYPE,
  display_name: "Bin",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [
    {
      name: "parts",
      type: "list[str]",
      has_default: true,
      default: [],
      description: "",
      searchable: true,
      row_editor: true,
    },
    { name: "tags", type: "list[str]", has_default: true, default: [], description: "" },
    { name: "gain", type: "float", has_default: true, default: 1.5, description: "" },
  ],
  default_n_inputs: 0,
  default_n_outputs: 1,
  port_shapes_in_default: [],
  port_shapes_out_default: [[]],
  tags: [],
  is_container: false,
  mask_capable: false,
  source: "workspace",
  input_names: [],
  output_names: [],
  dynamic_ports: true,
};

const rowsMock = vi.fn<(req: ParamRowsRequest, signal?: AbortSignal) => Promise<unknown>>();
const resolveMock =
  vi.fn<(typePath: string, params: Record<string, unknown>) => Promise<ResolvedPortShapes>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ schema_version: "blocks.v3", blocks: [META] })),
    paramRows: (req: ParamRowsRequest, signal?: AbortSignal) => rowsMock(req, signal),
    resolvePortShapes: (typePath: string, params: Record<string, unknown>) =>
      resolveMock(typePath, params),
  };
});

import { ParameterPanel } from "../src/components/ParameterPanel";
import { paramRowsQueue } from "../src/lib/paramRowsQueue";
import { _resetUserBlockPortsForTest, ensureUserBlockPorts } from "../src/lib/userBlockPorts";
import { useAppStore } from "../src/store/appStore";

function ports(params: Record<string, unknown>): ResolvedPortShapes {
  const n = Array.isArray(params.parts) ? params.parts.length : 0;
  return {
    n_inputs: n,
    n_outputs: 1,
    port_shapes_in: Array.from({ length: n }, () => []),
    port_shapes_out: [[]],
    input_names: [],
    output_names: [],
  };
}

/** ``name: part`` の行を説明する行エディタ。``?`` を含む行は error。 */
function fakeBlock(req: ParamRowsRequest): unknown {
  if (req.action === "describe") {
    const r = req as ParamRowsRequest<"describe">;
    return {
      columns: ["name", "part"],
      rows: r.rows.map((row) => ({
        cells: row.split(":").map((s) => s.trim()),
        error: row.includes("?") ? "unknown part" : null,
      })),
      ports: "input",
    };
  }
  if (req.action === "form") {
    return {
      variants: [{ id: "raw", label: "Row", fields: [{ key: "text", label: "Row", kind: "text" }] }],
      variant: "raw",
      values: {},
    };
  }
  if (req.action === "compose") {
    return { row: String((req as ParamRowsRequest<"compose">).values.text ?? "") };
  }
  return { columns: [], rows: [], truncated: false };
}

const PARTS = ["a: bolt", "b: nut", "c: pin"];

function model(): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "B1", type: TYPE, params: { parts: PARTS, tags: [], gain: 2 } },
      ...["s0", "s1", "s2"].map((id) => ({
        id,
        type: "flode.blocks.sources.Constant",
        params: { value: 1 },
      })),
    ],
    connections: [
      { src: "s0", src_idx: 0, dst: "B1", dst_idx: 0 },
      { src: "s1", src_idx: 0, dst: "B1", dst_idx: 1 },
      { src: "s2", src_idx: 0, dst: "B1", dst_idx: 2 },
    ],
    layout: {},
  };
}

async function renderPanel(): Promise<void> {
  useAppStore.setState({
    editingModel: model(),
    editingPath: [],
    selectedNodeId: "B1",
    history: { past: [], future: [] },
    lastMergeKey: null,
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
  await screen.findByTestId("block-header-user-summary");
}

function storeParts(): unknown {
  return useAppStore.getState().editingModel!.blocks.find((b) => b.id === "B1")!.params.parts;
}
function wiresIntoB1(): string[] {
  return useAppStore
    .getState()
    .editingModel!.connections.filter((c) => c.dst === "B1")
    .map((c) => `${c.src}->${c.dst_idx}`)
    .sort();
}
function tableRows(): HTMLElement[] {
  return screen.queryAllByTestId("param-rows-parts-table-row");
}
function button(name: string): HTMLButtonElement {
  return screen.getByTestId(`param-rows-parts-${name}`) as HTMLButtonElement;
}
/** describe の説明が表に出るまで待つ。 */
async function described(): Promise<void> {
  await waitFor(() => expect(tableRows()[0]?.querySelectorAll("td")).toHaveLength(2));
}

beforeEach(async () => {
  _resetUserBlockPortsForTest();
  rowsMock.mockReset();
  rowsMock.mockImplementation(async (req) => fakeBlock(req));
  resolveMock.mockReset();
  resolveMock.mockImplementation(async (_t, params) => ports(params));
  await ensureUserBlockPorts([{ type_path: TYPE, params: { parts: PARTS, tags: [], gain: 2 } }]);
});
afterEach(() => {
  cleanup();
  paramRowsQueue.reset();
  useAppStore.setState({ editingModel: null, selectedNodeId: null });
});

describe("ParameterPanel row editor", () => {
  it("renders a table for row_editor params, hides Search…, keeps JSON for others", async () => {
    await renderPanel();
    expect(screen.getByTestId("param-rows-parts-table")).toBeTruthy();
    expect(screen.queryByTestId("param-search-parts")).toBeNull();
    expect(screen.queryByTestId("param-input-parts")).toBeNull();
    expect(screen.getByTestId("param-input-tags").tagName).toBe("TEXTAREA");
    await described();
    expect(tableRows()[1]!.textContent).toContain("nut");
    const req = rowsMock.mock.calls[0]![0] as ParamRowsRequest<"describe">;
    // 他の引数値 (既定値で補完) を送り、編集中の引数自身は送らない
    expect(req).toMatchObject({ action: "describe", rows: PARTS, params: { tags: [], gain: 2 } });
    expect("parts" in req.params).toBe(false);
  });

  it("enables buttons by selection and position", async () => {
    await renderPanel();
    await described();
    expect(button("add").disabled).toBe(false);
    expect(button("text").disabled).toBe(false);
    expect(button("edit").disabled).toBe(true);
    expect(button("delete").disabled).toBe(true);
    fireEvent.click(tableRows()[0]!);
    expect(button("edit").disabled).toBe(false);
    expect(button("up").disabled).toBe(true);
    expect(button("down").disabled).toBe(false);
    fireEvent.click(tableRows()[2]!);
    expect(button("down").disabled).toBe(true);
  });

  it("deleting a wired middle row keeps later wires on their rows; one undo restores", async () => {
    await renderPanel();
    await described();
    fireEvent.click(tableRows()[1]!);
    fireEvent.click(button("delete"));
    await waitFor(() => expect(storeParts()).toEqual(["a: bolt", "c: pin"]));
    expect(wiresIntoB1()).toEqual(["s0->0", "s2->1"]);
    // 削除後は同じ位置を選ぶ
    await waitFor(() => expect(tableRows()[1]!.getAttribute("data-selected")).toBe("true"));
    expect(useAppStore.getState().history.past).toHaveLength(1);
    act(() => useAppStore.getState().undo());
    expect(storeParts()).toEqual(PARTS);
    expect(wiresIntoB1()).toEqual(["s0->0", "s1->1", "s2->2"]);
  });

  it("↑ swaps the rows and their wires", async () => {
    await renderPanel();
    await described();
    fireEvent.click(tableRows()[2]!);
    fireEvent.click(button("up"));
    await waitFor(() => expect(storeParts()).toEqual(["a: bolt", "c: pin", "b: nut"]));
    expect(wiresIntoB1()).toEqual(["s0->0", "s1->2", "s2->1"]);
  });

  it("adds a row through the dialog (wires unchanged)", async () => {
    await renderPanel();
    await described();
    fireEvent.click(button("add"));
    const text = await screen.findByTestId("param-row-field-text");
    fireEvent.change(text, { target: { value: "d: washer" } });
    const ok = screen.getByTestId("param-row-dialog-ok") as HTMLButtonElement;
    await waitFor(() => expect(ok.disabled).toBe(false));
    fireEvent.click(ok);
    await waitFor(() => expect(storeParts()).toEqual([...PARTS, "d: washer"]));
    expect(wiresIntoB1()).toEqual(["s0->0", "s1->1", "s2->2"]);
    expect(screen.queryByTestId("param-row-dialog-ok")).toBeNull();
  });

  it("text edit maps wires by number (no remap)", async () => {
    await renderPanel();
    await described();
    fireEvent.click(button("text"));
    fireEvent.change(screen.getByTestId("param-rows-text-input"), {
      target: { value: "a: bolt\nc: pin" },
    });
    fireEvent.click(screen.getByTestId("param-rows-text-ok"));
    await waitFor(() => expect(storeParts()).toEqual(["a: bolt", "c: pin"]));
    // 番号で対応: 2 番目のポートの配線は s1 のまま、3 番目は剪定
    expect(wiresIntoB1()).toEqual(["s0->0", "s1->1"]);
    expect(useAppStore.getState().history.past).toHaveLength(1);
  });

  it("describe failure shows an error and raw rows; delete then maps by number", async () => {
    rowsMock.mockImplementation(async (req) => {
      if (req.action === "describe") throw new ApiError(400, "400 boom", null, "data file missing");
      return fakeBlock(req);
    });
    await renderPanel();
    const err = await screen.findByTestId("param-rows-parts-describe-error");
    expect(err.textContent).toContain("data file missing");
    expect(tableRows()[0]!.textContent).toBe("a: bolt");
    fireEvent.click(tableRows()[0]!);
    fireEvent.click(button("delete"));
    await waitFor(() => expect(storeParts()).toEqual(["b: nut", "c: pin"]));
    expect(wiresIntoB1()).toEqual(["s0->0", "s1->1"]);
  });

  it("marks error rows red", async () => {
    await renderPanel();
    await described();
    fireEvent.click(button("text"));
    fireEvent.change(screen.getByTestId("param-rows-text-input"), {
      target: { value: "a: bolt\nz: ???" },
    });
    await ensureUserBlockPorts([
      { type_path: TYPE, params: { parts: ["a: bolt", "z: ???"], tags: [], gain: 2 } },
    ]);
    fireEvent.click(screen.getByTestId("param-rows-text-ok"));
    await waitFor(() => expect(tableRows()[1]?.getAttribute("data-error")).toBe("true"));
    expect(tableRows()[1]!.getAttribute("title")).toBe("unknown part");
  });

  it("disables the row buttons while the ports are being resolved", async () => {
    let release: (() => void) | null = null;
    resolveMock.mockImplementation(
      (_t, params) =>
        new Promise((resolve) => {
          release = () => resolve(ports(params));
        }),
    );
    await renderPanel();
    await described();
    fireEvent.click(tableRows()[0]!);
    fireEvent.click(button("delete"));
    await waitFor(() => expect(button("add").disabled).toBe(true));
    expect(button("text").disabled).toBe(true);
    expect(screen.getByTestId("param-rows-parts-busy")).toBeTruthy();
    // 確定前は store は変わらない
    expect(storeParts()).toEqual(PARTS);
    await act(async () => {
      release!();
    });
    await waitFor(() => expect(storeParts()).toEqual(["b: nut", "c: pin"]));
    expect(wiresIntoB1()).toEqual(["s1->0", "s2->1"]);
    expect(button("add").disabled).toBe(false);
  });

  it("a regular edit while a row operation is pending keeps the row remap", async () => {
    let release: (() => void) | null = null;
    resolveMock.mockImplementation(
      (_t, params) =>
        new Promise((resolve) => {
          release = () => resolve(ports(params));
        }),
    );
    await renderPanel();
    await described();
    fireEvent.click(tableRows()[1]!);
    fireEvent.click(button("delete"));
    await waitFor(() => expect(button("add").disabled).toBe(true));
    // 応答待ちの間に別の引数を編集 (未確定の値を土台にする)
    fireEvent.change(screen.getByTestId("param-input-gain"), { target: { value: "5" } });
    await act(async () => {
      release!();
    });
    await waitFor(() => expect(storeParts()).toEqual(["a: bolt", "c: pin"]));
    const params = useAppStore.getState().editingModel!.blocks[0]!.params;
    expect(params.gain).toBe(5);
    // 行の削除の付け替えが消えていない
    expect(wiresIntoB1()).toEqual(["s0->0", "s2->1"]);
    expect(useAppStore.getState().history.past).toHaveLength(1);
  });

  it("disables row-moving operations until the first describe arrives, then remaps wires", async () => {
    // 最初の describe を止めておく (ports が分からない間)
    let releaseDescribe: (() => void) | null = null;
    rowsMock.mockImplementation((req) =>
      req.action === "describe" && releaseDescribe === null
        ? new Promise((resolve) => {
            releaseDescribe = () => resolve(fakeBlock(req));
          })
        : Promise.resolve(fakeBlock(req)),
    );
    await renderPanel();
    await waitFor(() => expect(releaseDescribe).not.toBeNull());
    fireEvent.click(tableRows()[1]!);
    // 番号で動かすと配線が別の行へずれるので、削除・↑・↓・編集はできない。追加はずらさない
    expect(button("delete").disabled).toBe(true);
    expect(button("up").disabled).toBe(true);
    expect(button("down").disabled).toBe(true);
    expect(button("edit").disabled).toBe(true);
    expect(button("add").disabled).toBe(false);
    fireEvent.click(button("delete"));
    fireEvent.doubleClick(tableRows()[1]!);
    fireEvent.keyDown(screen.getByTestId("param-rows-parts-table"), { key: "Enter" });
    expect(screen.queryByTestId("param-row-dialog-ok")).toBeNull();
    expect(storeParts()).toEqual(PARTS);
    expect(screen.getByTestId("param-rows-parts-ports-pending")).toBeTruthy();

    await act(async () => {
      releaseDescribe!();
    });
    await described();
    expect(screen.queryByTestId("param-rows-parts-ports-pending")).toBeNull();
    fireEvent.click(tableRows()[1]!);
    fireEvent.click(button("delete"));
    await waitFor(() => expect(storeParts()).toEqual(["a: bolt", "c: pin"]));
    expect(wiresIntoB1()).toEqual(["s0->0", "s2->1"]);
    // 操作の直後 (次の describe の前) も、覚えた ports で操作できる (ボタンがちらつかない)
    expect(button("delete").disabled).toBe(false);
  });
});

describe("ParamRowsEditor dialogs", () => {
  /** 行と busy を外から差し替えられる ParamRowsEditor。 */
  async function renderEditor(initial: { rows: string[]; busy: boolean }): Promise<{
    onApply: ReturnType<typeof vi.fn>;
    update: (next: { rows?: string[]; busy?: boolean }) => void;
  }> {
    const { ParamRowsEditor } = await import("../src/components/ParamRowsEditor");
    const state = { ...initial };
    const onApply = vi.fn();
    const el = (): JSX.Element => (
      <ParamRowsEditor
        typePath={TYPE}
        blockId="B1"
        param="parts"
        rows={state.rows}
        otherParams={{}}
        busy={state.busy}
        readRows={() => [...state.rows]}
        readParams={() => ({})}
        onApply={onApply}
      />
    );
    const view = render(el());
    await described();
    return {
      onApply,
      update: (next) => {
        Object.assign(state, next);
        view.rerender(el());
      },
    };
  }

  async function openEditDialog(index: number, text: string): Promise<HTMLButtonElement> {
    fireEvent.click(tableRows()[index]!);
    fireEvent.click(button("edit"));
    const input = await screen.findByTestId("param-row-field-text");
    fireEvent.change(input, { target: { value: text } });
    const ok = screen.getByTestId("param-row-dialog-ok") as HTMLButtonElement;
    await waitFor(() => expect(ok.disabled).toBe(false));
    return ok;
  }

  it("row dialog keeps the input while busy (OK disabled), applies once ready", async () => {
    const ed = await renderEditor({ rows: PARTS, busy: false });
    const ok = await openEditDialog(1, "b: washer");
    ed.update({ busy: true });
    expect(ok.disabled).toBe(true);
    fireEvent.click(ok);
    expect(ed.onApply).not.toHaveBeenCalled();
    expect(screen.getByTestId("param-row-field-text")).toBeTruthy();
    ed.update({ busy: false });
    expect(ok.disabled).toBe(false);
    fireEvent.click(ok);
    expect(ed.onApply).toHaveBeenCalledWith(["a: bolt", "b: washer", "c: pin"], [
      { side: "input", map: [0, 1, 2] },
    ]);
    expect(screen.queryByTestId("param-row-dialog-ok")).toBeNull();
  });

  it("text dialog keeps the input while busy (OK disabled), applies once ready", async () => {
    const ed = await renderEditor({ rows: PARTS, busy: false });
    fireEvent.click(button("text"));
    fireEvent.change(screen.getByTestId("param-rows-text-input"), {
      target: { value: "a: bolt" },
    });
    ed.update({ busy: true });
    const ok = screen.getByTestId("param-rows-text-ok") as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    fireEvent.click(ok);
    expect(ed.onApply).not.toHaveBeenCalled();
    expect((screen.getByTestId("param-rows-text-input") as HTMLTextAreaElement).value).toBe(
      "a: bolt",
    );
    ed.update({ busy: false });
    fireEvent.click(ok);
    expect(ed.onApply).toHaveBeenCalledWith(["a: bolt"], []);
  });

  it("edit OK does nothing when the edited row changed after the dialog opened", async () => {
    const ed = await renderEditor({ rows: PARTS, busy: false });
    const ok = await openEditDialog(1, "b: washer");
    // 開いている間に行が変わった (Undo 等)。番号は範囲内のまま
    ed.update({ rows: ["a: bolt", "x: other", "c: pin"] });
    fireEvent.click(ok);
    expect(ed.onApply).not.toHaveBeenCalled();
    expect(screen.queryByTestId("param-row-dialog-ok")).toBeNull();
  });
});
