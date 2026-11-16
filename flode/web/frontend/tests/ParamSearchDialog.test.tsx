// ADR-0085 §4-B / §4-C, SPEC-0036 U-1〜U-7: Inspector の「探す…」と引数の値の検索ダイアログ。
// - 検索を宣言した (searchable) 文字列リストの引数にだけボタンが出る
// - 表の並び順で、既にある値を除いて末尾に足す (Undo できる)。追加後は同じ検索語で再検索する
// - 検索関数のエラーはダイアログ内に出し、ダイアログは閉じない
// - ブロックの選択が変わると閉じる

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../src/api/client";
import { PARAM_SEARCH_RETRY_MS } from "../src/lib/paramSearch";
import type {
  BlockMetadata,
  FlwModel,
  ParamSearchRequest,
  ParamSearchResponse,
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

const TYPE = "flode_ws.parts.Catalog";

const META: BlockMetadata = {
  type_path: TYPE,
  display_name: "Catalog",
  category: "",
  icon: "default",
  docstring_summary: "",
  params_spec: [
    {
      name: "items",
      type: "list[str]",
      has_default: true,
      default: [],
      description: "",
      searchable: true,
    },
    { name: "tags", type: "list[str]", has_default: true, default: [], description: "" },
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
};

const searchMock =
  vi.fn<(req: ParamSearchRequest, signal?: AbortSignal) => Promise<ParamSearchResponse>>();
vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ schema_version: "blocks.v3", blocks: [META] })),
    searchParamValues: (req: ParamSearchRequest, signal?: AbortSignal) => searchMock(req, signal),
  };
});

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";

/** 部品カタログ風の検索関数: ``current`` に同じ名前があれば ``_2`` を付ける。 */
function catalogSearch(req: ParamSearchRequest): ParamSearchResponse {
  const parts = ["bolt", "nut", "washer"].filter((p) => p.includes(req.query));
  const used = new Set(req.current.map((c) => c.split(":")[0]));
  return {
    columns: ["part", "stock"],
    rows: parts.map((p, i) => {
      const name = used.has(p) ? `${p}_2` : p;
      return { cells: [p, 10 * (i + 1)], value: `${name}: part=${p}` };
    }),
    truncated: false,
  };
}

function model(params: Record<string, unknown>): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks: [
      { id: "B1", type: TYPE, params },
      { id: "B2", type: TYPE, params: { items: [], tags: [] } },
    ],
    connections: [],
    layout: {},
  };
}

async function renderPanel(params: Record<string, unknown>): Promise<void> {
  useAppStore.setState({
    editingModel: model(params),
    editingPath: [],
    selectedNodeId: "B1",
    // 前のテストの履歴と合体キー (同じブロック・引数の編集は 1 ステップに合体する) を残さない
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

function items(): unknown {
  return useAppStore.getState().editingModel!.blocks[0]!.params.items;
}

/** ダイアログを開いて検索語を入れ、Enter で即時に検索する。 */
async function openAndSearch(query: string): Promise<void> {
  fireEvent.click(await screen.findByTestId("param-search-items"));
  const input = screen.getByTestId("param-search-query");
  fireEvent.change(input, { target: { value: query } });
  await act(async () => {
    fireEvent.keyDown(input, { key: "Enter" });
  });
}

function tableRow(value: string): HTMLElement {
  return screen.getAllByTestId("param-search-table-row").find((r) => r.dataset.key === value)!;
}

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockImplementation(async (req) => catalogSearch(req));
});
afterEach(() => cleanup());

describe("ParameterPanel: search button", () => {
  it("shows the button only for searchable string-list parameters", async () => {
    await renderPanel({ items: ["a: part=a"], tags: [] });
    expect(await screen.findByTestId("param-search-items")).toBeTruthy();
    expect(screen.queryByTestId("param-search-tags")).toBeNull();
  });

  it("does not show the button when the value is not a list of strings", async () => {
    await renderPanel({ items: [1, 2], tags: [] });
    await screen.findByTestId("param-input-items");
    expect(screen.queryByTestId("param-search-items")).toBeNull();
  });
});

describe("ParamSearchDialog", () => {
  it("does not send an empty query", async () => {
    await renderPanel({ items: [], tags: [] });
    fireEvent.click(await screen.findByTestId("param-search-items"));
    const input = screen.getByTestId("param-search-query");
    fireEvent.change(input, { target: { value: "   " } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
    });
    expect(searchMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("param-search-table-empty").textContent).toBe(
      "inspector.param_search.empty_query",
    );
  });

  it("appends the selected values in table order and searches again", async () => {
    await renderPanel({ items: ["keep: part=x"], tags: [] });
    await openAndSearch("t"); // bolt, nut (washer は含まない)
    await screen.findAllByTestId("param-search-table-row");
    expect(searchMock.mock.calls[0]![0]).toMatchObject({
      type_path: TYPE,
      param: "items",
      query: "t",
      current: ["keep: part=x"],
    });

    // 選ぶ順は nut → bolt でも、表の順 (bolt, nut) で足す
    fireEvent.click(within(tableRow("nut: part=nut")).getByText("nut"));
    fireEvent.click(within(tableRow("bolt: part=bolt")).getByText("bolt"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("param-search-add"));
    });

    expect(items()).toEqual(["keep: part=x", "bolt: part=bolt", "nut: part=nut"]);
    // 同じ検索語で、追加後の current を渡して再検索する
    await waitFor(() => expect(searchMock).toHaveBeenCalledTimes(2));
    expect(searchMock.mock.calls[1]![0]).toMatchObject({
      query: "t",
      current: ["keep: part=x", "bolt: part=bolt", "nut: part=nut"],
    });
    // ブロックの提案が変わり (bolt_2)、選択は空になっている
    await waitFor(() => expect(tableRow("bolt_2: part=bolt")).toBeTruthy());
    expect(screen.getByTestId("param-search-add")).toHaveProperty("disabled", true);

    // Undo で追加の前に戻る (通常の引数の変更と同じ扱い)
    act(() => useAppStore.getState().undo());
    expect(items()).toEqual(["keep: part=x"]);
  });

  it("cannot select or add stale proposals until the re-search responds", async () => {
    await renderPanel({ items: [], tags: [] });
    await openAndSearch("t");
    await screen.findAllByTestId("param-search-table-row");
    fireEvent.click(within(tableRow("bolt: part=bolt")).getByText("bolt"));

    // 再検索の応答を止めておく
    let release: () => void = () => undefined;
    searchMock.mockImplementation(
      (req) =>
        new Promise((resolve) => {
          release = () => resolve(catalogSearch(req));
        }),
    );
    await act(async () => {
      fireEvent.click(screen.getByTestId("param-search-add"));
    });
    expect(items()).toEqual(["bolt: part=bolt"]);

    // 古い提案 (nut: part=nut は current と衝突しないが、提案自体が古い) は選べず、追加もできない
    const stale = tableRow("nut: part=nut");
    expect(stale.dataset.disabled).toBe("true");
    fireEvent.click(within(stale).getByText("nut"));
    const add = screen.getByTestId("param-search-add");
    expect(add).toHaveProperty("disabled", true);
    fireEvent.click(add);
    expect(items()).toEqual(["bolt: part=bolt"]);
    expect(screen.getByTestId("param-search-status").textContent).toBe(
      "inspector.param_search.searching",
    );

    await act(async () => release());
    await waitFor(() => expect(tableRow("bolt_2: part=bolt")).toBeTruthy());
    const fresh = tableRow("nut: part=nut");
    expect(fresh.dataset.disabled).toBeUndefined();
    fireEvent.click(within(fresh).getByText("nut"));
    expect(screen.getByTestId("param-search-add")).toHaveProperty("disabled", false);
  });

  it("undoes an append in one step", async () => {
    await renderPanel({ items: ["keep: part=x"], tags: [] });
    await openAndSearch("t");
    await screen.findAllByTestId("param-search-table-row");
    fireEvent.click(within(tableRow("bolt: part=bolt")).getByText("bolt"));
    fireEvent.click(within(tableRow("nut: part=nut")).getByText("nut"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("param-search-add"));
    });
    expect(items()).toEqual(["keep: part=x", "bolt: part=bolt", "nut: part=nut"]);
    act(() => useAppStore.getState().undo());
    expect(items()).toEqual(["keep: part=x"]);
    act(() => useAppStore.getState().redo());
    expect(items()).toEqual(["keep: part=x", "bolt: part=bolt", "nut: part=nut"]);
  });

  it("retries after a 409 and shows the result", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      searchMock
        .mockRejectedValueOnce(new ApiError(409, "409 busy", null, "busy"))
        .mockImplementation(async (req) => catalogSearch(req));
      await renderPanel({ items: [], tags: [] });
      await openAndSearch("t");
      expect(searchMock).toHaveBeenCalledTimes(1);
      // 再試行を待つ間はエラーではなく「検索中…」
      expect(screen.getByTestId("param-search-status").textContent).toBe(
        "inspector.param_search.searching",
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(PARAM_SEARCH_RETRY_MS);
      });
      expect(searchMock).toHaveBeenCalledTimes(2);
      expect(searchMock.mock.calls[1]![0]).toMatchObject({ query: "t" });
      await waitFor(() => expect(tableRow("bolt: part=bolt")).toBeTruthy());
    } finally {
      vi.useRealTimers();
    }
  });

  it("dims rows already in the parameter and never adds an existing value", async () => {
    // 既にある値をそのまま返すブロック (衝突回避をしない)
    searchMock.mockImplementation(async () => ({
      columns: ["part"],
      rows: [
        { cells: ["bolt"], value: "bolt: part=bolt" },
        { cells: ["nut"], value: "nut: part=nut" },
      ],
      truncated: false,
    }));
    await renderPanel({ items: ["bolt: part=bolt"], tags: [] });
    await openAndSearch("o");
    await screen.findAllByTestId("param-search-table-row");

    const existing = tableRow("bolt: part=bolt");
    expect(existing.dataset.disabled).toBe("true");
    fireEvent.click(within(existing).getByText("bolt"));
    expect(screen.getByTestId("param-search-add")).toHaveProperty("disabled", true);

    fireEvent.click(within(tableRow("nut: part=nut")).getByText("nut"));
    await act(async () => {
      fireEvent.click(screen.getByTestId("param-search-add"));
    });
    expect(items()).toEqual(["bolt: part=bolt", "nut: part=nut"]);
  });

  it("shows the count, and a hint when the result is truncated", async () => {
    searchMock.mockImplementation(async () => ({
      columns: ["part"],
      rows: [{ cells: ["bolt"], value: "bolt" }],
      truncated: true,
    }));
    await renderPanel({ items: [], tags: [] });
    await openAndSearch("b");
    await waitFor(() =>
      expect(screen.getByTestId("param-search-status").textContent).toBe(
        'inspector.param_search.truncated:{"count":1}',
      ),
    );
  });

  it("shows 'no results' for an empty result", async () => {
    searchMock.mockImplementation(async () => ({ columns: ["part"], rows: [], truncated: false }));
    await renderPanel({ items: [], tags: [] });
    await openAndSearch("zzz");
    await waitFor(() =>
      expect(screen.getByTestId("param-search-status").textContent).toBe(
        "inspector.param_search.no_results",
      ),
    );
  });

  it("shows a search function error inside the dialog without closing it", async () => {
    searchMock.mockRejectedValue(
      new ApiError(400, "400 RuntimeError: index missing", null, "RuntimeError: index missing"),
    );
    await renderPanel({ items: [], tags: [] });
    await openAndSearch("b");
    await waitFor(() =>
      expect(screen.getByTestId("param-search-status").textContent).toBe(
        "RuntimeError: index missing",
      ),
    );
    expect(screen.getByTestId("param-search-status").getAttribute("role")).toBe("alert");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("closes when another block is selected", async () => {
    await renderPanel({ items: [], tags: [] });
    fireEvent.click(await screen.findByTestId("param-search-items"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    act(() => useAppStore.setState({ selectedNodeId: "B2" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // 元のブロックに戻っても開き直さない
    act(() => useAppStore.setState({ selectedNodeId: "B1" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes with the close button", async () => {
    await renderPanel({ items: [], tags: [] });
    fireEvent.click(await screen.findByTestId("param-search-items"));
    fireEvent.click(screen.getByTestId("param-search-close"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
