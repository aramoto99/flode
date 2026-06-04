// SPEC-0011 §テスト戦略: ParameterPanel が array / long-string を
// JsonArrayEditor / ExpressionEditor に振り分けることの統合確認。

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ParameterPanel } from "../src/components/ParameterPanel";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (k: string, params?: Record<string, string> | string) =>
      typeof params === "string" ? params : k,
  }),
}));

vi.mock("../src/api/client", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    listBlockMetadata: vi.fn(async () => ({ blocks: [] })),
  };
});

function makeLookupModel(): FlwModel {
  return {
    schema_version: "0.9",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "Lookup_1",
        type: "pyflw.blocks.lookup.LookupTable1D",
        params: {
          breakpoints: [0.0, 1.0],
          table: [0.0, 1.0],
          interpolation: "linear",
          extrapolation: "clip",
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function makeFcnModel(expression: string): FlwModel {
  return {
    schema_version: "0.9",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "Fcn_1",
        type: "pyflw.blocks.userfunc.Fcn",
        params: {
          expression,
          n_inputs: 1,
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function makeStateSpaceModel(): FlwModel {
  // SPEC-0017: 2-D 数値配列は GridEditor で editable に昇格
  return {
    schema_version: "0.9",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "SS_1",
        type: "pyflw.blocks.continuous.StateSpace",
        params: {
          A: [
            [0, 1],
            [-1, -2],
          ],
          B: [[0], [1]],
          C: [[1, 0]],
          D: [[0]],
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function makeLookupTable2DModel(): FlwModel {
  return {
    schema_version: "0.9",
    simulator: {
      t_end: 1,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      {
        id: "LT2D_1",
        type: "pyflw.blocks.lookup.LookupTable2D",
        params: {
          breakpoints_row: [0.0, 1.0, 2.0],
          breakpoints_col: [0.0, 0.5, 1.0],
          table: [
            [0.0, 1.0, 2.0],
            [3.0, 4.0, 5.0],
            [6.0, 7.0, 8.0],
          ],
          interpolation: "linear",
          extrapolation: "clip",
        },
      },
    ],
    connections: [],
    layout: {},
  };
}

function renderPanel(): ReturnType<typeof render> {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ParameterPanel modelId="test" />
    </QueryClientProvider>,
  );
}

afterEach(() => cleanup());

describe("ParameterPanel: SPEC-0011 array & expression editor branches", () => {
  it("renders JsonArrayEditor (textarea) for LookupTable1D.breakpoints", () => {
    useAppStore.setState({
      editingModel: makeLookupModel(),
      editingPath: [],
      selectedNodeId: "Lookup_1",
    });
    renderPanel();
    const input = screen.getByTestId("param-input-breakpoints");
    // JsonArrayEditor は textarea を render する (既存 <input> 経路と区別)
    expect(input.tagName).toBe("TEXTAREA");
    expect((input as HTMLTextAreaElement).value).toBe("[0,1]");
  });

  it("commits edited breakpoints on blur", () => {
    useAppStore.setState({
      editingModel: makeLookupModel(),
      editingPath: [],
      selectedNodeId: "Lookup_1",
    });
    renderPanel();
    const ta = screen.getByTestId(
      "param-input-breakpoints",
    ) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "[0, 1, 2]" } });
    fireEvent.blur(ta);

    const m = useAppStore.getState().editingModel!;
    const blk = m.blocks.find((b) => b.id === "Lookup_1")!;
    expect(blk.params.breakpoints).toEqual([0, 1, 2]);
  });

  it("renders short string input (not ExpressionEditor) for default expression", () => {
    // default "u[0]" は < 40 chars → single-line input にとどまる
    useAppStore.setState({
      editingModel: makeFcnModel("u[0]"),
      editingPath: [],
      selectedNodeId: "Fcn_1",
    });
    renderPanel();
    const input = screen.getByTestId("param-input-expression");
    expect(input.tagName).toBe("INPUT");
  });

  it("renders ExpressionEditor (textarea) for long expression (>40 chars)", () => {
    const longExpr = "u[0] * (1 + 0.05 * u[0]**2) + sin(t) * cos(t)"; // 45 chars
    useAppStore.setState({
      editingModel: makeFcnModel(longExpr),
      editingPath: [],
      selectedNodeId: "Fcn_1",
    });
    renderPanel();
    const input = screen.getByTestId("param-input-expression");
    expect(input.tagName).toBe("TEXTAREA");
    expect((input as HTMLTextAreaElement).value).toBe(longExpr);
  });

  it("renders ExpressionEditor for multi-line expression", () => {
    // 改行を含む string は短くても ExpressionEditor で render
    useAppStore.setState({
      editingModel: makeFcnModel("u[0]\nu[1]"),
      editingPath: [],
      selectedNodeId: "Fcn_1",
    });
    renderPanel();
    const input = screen.getByTestId("param-input-expression");
    expect(input.tagName).toBe("TEXTAREA");
  });

  it("isLongStringParam threshold: 40 chars stays short (input)", () => {
    // 40 chars ぴったりは short string 経路 (single-line <input>)
    const expr = "a".repeat(40);
    useAppStore.setState({
      editingModel: makeFcnModel(expr),
      editingPath: [],
      selectedNodeId: "Fcn_1",
    });
    renderPanel();
    expect(
      screen.getByTestId("param-input-expression").tagName,
    ).toBe("INPUT");
  });

  it("isLongStringParam threshold: 41 chars upgrades to ExpressionEditor", () => {
    // 41 chars で textarea 経路に upgrade
    const expr = "a".repeat(41);
    useAppStore.setState({
      editingModel: makeFcnModel(expr),
      editingPath: [],
      selectedNodeId: "Fcn_1",
    });
    renderPanel();
    expect(
      screen.getByTestId("param-input-expression").tagName,
    ).toBe("TEXTAREA");
  });

  it("SPEC-0017: 2-D numeric arrays render GridEditor (StateSpace.A)", () => {
    // SPEC-0017 で 2-D 数値配列が editable に昇格 (SPEC-0011 時点では readOnly)
    useAppStore.setState({
      editingModel: makeStateSpaceModel(),
      editingPath: [],
      selectedNodeId: "SS_1",
    });
    renderPanel();
    // GridEditor の base testid (param-input-A) が table を含む
    expect(screen.queryByTestId("param-input-A-table")).toBeTruthy();
  });

  it("SPEC-0017: LookupTable2D.table renders GridEditor with shape link", () => {
    useAppStore.setState({
      editingModel: makeLookupTable2DModel(),
      editingPath: [],
      selectedNodeId: "LT2D_1",
    });
    renderPanel();
    // table param が GridEditor で render される
    expect(screen.queryByTestId("param-input-table-table")).toBeTruthy();
    // breakpoints_row / breakpoints_col は JsonArrayEditor (textarea)
    expect(
      screen.queryByTestId("param-input-breakpoints_row")?.tagName,
    ).toBe("TEXTAREA");
    expect(
      screen.queryByTestId("param-input-breakpoints_col")?.tagName,
    ).toBe("TEXTAREA");
  });

  it("SPEC-0017: GridEditor cell edit commits to model", () => {
    useAppStore.setState({
      editingModel: makeLookupTable2DModel(),
      editingPath: [],
      selectedNodeId: "LT2D_1",
    });
    renderPanel();
    const cell = screen.getByTestId(
      "param-input-table-cell-1-1",
    ) as HTMLInputElement;
    fireEvent.change(cell, { target: { value: "999" } });
    fireEvent.blur(cell);
    const m = useAppStore.getState().editingModel!;
    const blk = m.blocks.find((b) => b.id === "LT2D_1")!;
    expect((blk.params.table as number[][])[1]![1]).toBe(999);
  });
});
