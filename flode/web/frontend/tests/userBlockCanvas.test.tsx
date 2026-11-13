// ADR-0081 §8-D / §論点 3 / §論点 4 (U5): キャンバス上のユーザーブロックとプレースホルダ。
// - ユーザーブロック: 汎用矩形 + 表示名 + ポート名、サイズはポート数と名前の長さから自動
// - 組み込みブロックの描画・サイズは変わらない、型名の末尾一致で組み込み扱いにならない
// - プレースホルダ: ポート数を接続から導く、直前に見たメタデータで形を保つ
// - 超過ポート: max(registry, 接続) で描き、超えた側の配線をエラー表示 (自動では消さない)
// - ユーザーブロックはパラメータ編集で配線を剪定しない

import { ReactFlowProvider } from "@xyflow/react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BlockNodeView } from "../src/components/BlockNodeView";
import {
  getUserBlockShape,
  USER_BLOCK_MAX_WIDTH,
  USER_BLOCK_MIN_HEIGHT,
  USER_BLOCK_MIN_WIDTH,
} from "../src/lib/blockShapes";
import {
  DIAGRAM_EDGE_STYLE,
  DIAGRAM_EDGE_STYLE_ERROR,
  modelToDiagram,
  type BlockNodeData,
} from "../src/lib/diagramConverter";
import { canPruneOnParamChange, resolvePortCounts } from "../src/lib/dynamicPorts";
import { getDefaultPortShapes, indexRegistry } from "../src/lib/portShapeValidate";
import {
  _resetLastSeenBlockMetadataForTest,
  lastSeenBlockMetadata,
  rememberBlockMetadata,
} from "../src/lib/userBlockModel";
import type { BlockMetadata, FlwModel } from "../src/types/api";

vi.mock("../src/store/appStore", () => ({
  useAppStore: (
    selector: (s: { scopes: Record<string, never>; renameRequest: null }) => unknown,
  ) => selector({ scopes: {}, renameRequest: null }),
  updateBlockSize: vi.fn(),
  renameBlockInEditing: vi.fn(() => null),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

const USER_TYPE = "flode_ws.filters.Mixer";
// X-1 で禁止されているが、判定ロジック側でも組み込み Sum と取り違えないこと
const SUFFIX_TYPE = "flode_ws.filters.Sum";
const SINK_TYPE = "flode_ws.io.CsvWriter";
const SOURCE_TYPE = "flode_ws.io.Ticker";
const GAIN_TYPE = "flode.blocks.mathops.Gain";
const SUM_TYPE = "flode.blocks.mathops.Sum";
const GONE_TYPE = "flode_ws.filters.Gone";

function meta(over: Partial<BlockMetadata>): BlockMetadata {
  return {
    type_path: GAIN_TYPE,
    display_name: "Gain",
    category: "math",
    icon: "default",
    docstring_summary: "",
    params_spec: [],
    default_n_inputs: 1,
    default_n_outputs: 1,
    port_shapes_in_default: [[]],
    port_shapes_out_default: [[]],
    tags: [],
    is_container: false,
    mask_capable: false,
    source: "builtin",
    ...over,
  };
}

const USER_META = meta({
  type_path: USER_TYPE,
  display_name: "Mixer",
  display_name_i18n: { ja: "ミキサー" },
  source: "workspace",
  default_n_inputs: 2,
  default_n_outputs: 1,
  port_shapes_in_default: [[], [3]],
  port_shapes_out_default: [[]],
  input_names: ["left", ""],
  output_names: ["mix"],
});
const SUFFIX_META = meta({
  type_path: SUFFIX_TYPE,
  display_name: "My sum",
  source: "workspace",
  default_n_inputs: 1,
  default_n_outputs: 1,
});
const SINK_META = meta({
  type_path: SINK_TYPE,
  display_name: "CSV writer",
  source: "workspace",
  default_n_inputs: 1,
  default_n_outputs: 0,
  port_shapes_out_default: [],
  input_names: ["value"],
  tags: ["sink"],
});
const SOURCE_META = meta({
  type_path: SOURCE_TYPE,
  display_name: "Ticker",
  source: "dir:lab",
  default_n_inputs: 0,
  default_n_outputs: 1,
  port_shapes_in_default: [],
  tags: ["source"],
});
const GAIN_META = meta({});
const SUM_META = meta({ type_path: SUM_TYPE, display_name: "Sum", default_n_inputs: 2 });
const REGISTRY = indexRegistry([
  USER_META,
  SUFFIX_META,
  SINK_META,
  SOURCE_META,
  GAIN_META,
  SUM_META,
]);

function model(
  blocks: FlwModel["blocks"],
  connections: FlwModel["connections"] = [],
): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks,
    connections,
    layout: {},
  };
}

function nodeOf(m: FlwModel, id: string, registry = REGISTRY, lastSeen?: Map<string, BlockMetadata>) {
  const { nodes } = modelToDiagram(m, registry, lastSeen ? { lastSeen } : {});
  const n = nodes.find((x) => x.id === id);
  if (!n) throw new Error(`node ${id} not found`);
  return n;
}

function renderNode(id: string, data: BlockNodeData) {
  const props = {
    id,
    data,
    selected: false,
    type: "blockNode",
    zIndex: 0,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
    dragging: false,
    draggable: true,
    selectable: true,
    deletable: true,
  };
  return render(
    <ReactFlowProvider>
      <BlockNodeView {...props} />
    </ReactFlowProvider>,
  );
}

afterEach(() => cleanup());

describe("user block nodes (modelToDiagram)", () => {
  it("uses the registry port counts and a generic rect sized from the names", () => {
    const n = nodeOf(model([{ id: "mx", type: USER_TYPE, params: {} }]), "mx");
    expect(n.data.nInputs).toBe(2);
    expect(n.data.nOutputs).toBe(1);
    expect(n.data.userBlock?.kind).toBe("user");
    expect(n.width).toBeGreaterThanOrEqual(USER_BLOCK_MIN_WIDTH);
    expect(n.width).toBeLessThanOrEqual(USER_BLOCK_MAX_WIDTH);
    expect(n.height).toBeGreaterThanOrEqual(USER_BLOCK_MIN_HEIGHT);
  });

  it("grows with longer names and more ports, within the bounds", () => {
    const small = getUserBlockShape({ titles: ["A"], inputs: [], outputs: [] }, 1, 1);
    expect(small).toEqual({ kind: "rect", width: USER_BLOCK_MIN_WIDTH, height: USER_BLOCK_MIN_HEIGHT });
    const wide = getUserBlockShape(
      { titles: ["A fairly long display name"], inputs: ["input_signal"], outputs: ["output"] },
      1,
      1,
    );
    expect(wide.width).toBeGreaterThan(USER_BLOCK_MIN_WIDTH);
    const huge = getUserBlockShape({ titles: ["x".repeat(200)], inputs: [], outputs: [] }, 1, 1);
    expect(huge.width).toBe(USER_BLOCK_MAX_WIDTH);
    const tall = getUserBlockShape({ titles: ["A"], inputs: [], outputs: [] }, 6, 1);
    expect(tall.height).toBeGreaterThan(USER_BLOCK_MIN_HEIGHT);
    // 全角は半角より広く見積もる (言語を切り替えても形が変わらないよう、全候補の最長で決める)
    const ja = getUserBlockShape({ titles: ["Mixer", "とても長いミキサーの名前"], inputs: [], outputs: [] }, 1, 1);
    const en = getUserBlockShape({ titles: ["Mixer"], inputs: [], outputs: [] }, 1, 1);
    expect(ja.width).toBeGreaterThan(en.width);
  });

  it("draws sinks and sources without the missing side", () => {
    const sink = nodeOf(model([{ id: "w", type: SINK_TYPE, params: {} }]), "w");
    expect([sink.data.nInputs, sink.data.nOutputs]).toEqual([1, 0]);
    const source = nodeOf(model([{ id: "s", type: SOURCE_TYPE, params: {} }]), "s");
    expect([source.data.nInputs, source.data.nOutputs]).toEqual([0, 1]);
    expect(source.width).toBeGreaterThanOrEqual(USER_BLOCK_MIN_WIDTH);
  });

  it("does not change builtin nodes", () => {
    const m = model([
      { id: "g", type: GAIN_TYPE, params: { k: 2 } },
      { id: "s", type: SUM_TYPE, params: { signs: "+-+" } },
    ]);
    const withUser = modelToDiagram(
      { ...m, blocks: [...m.blocks, { id: "mx", type: USER_TYPE, params: {} }] },
      REGISTRY,
    ).nodes;
    const without = modelToDiagram(m, REGISTRY).nodes;
    for (const id of ["g", "s"]) {
      const a = withUser.find((n) => n.id === id)!;
      const b = without.find((n) => n.id === id)!;
      expect([a.width, a.height, a.data.nInputs, a.data.nOutputs]).toEqual([
        b.width,
        b.height,
        b.data.nInputs,
        b.data.nOutputs,
      ]);
      expect(a.data.userBlock).toBeUndefined();
    }
    // Gain は三角形のまま (56×48)、Sum は signs から 3 入力
    expect([without[0]!.width, without[0]!.height]).toEqual([56, 48]);
    expect(without[1]!.data.nInputs).toBe(3);
  });

  it("does not treat a user type ending in .Sum as the builtin Sum", () => {
    const n = nodeOf(model([{ id: "x", type: SUFFIX_TYPE, params: { signs: "+++" } }]), "x");
    expect(n.data.nInputs).toBe(1); // signs ではなく registry の数
    expect(n.data.userBlock?.kind).toBe("user");
    expect(resolvePortCounts(SUFFIX_TYPE, { signs: "+++" }, SUFFIX_META)).toEqual({
      nInputs: 1,
      nOutputs: 1,
    });
    // 組み込み Sum は従来どおり
    expect(resolvePortCounts(SUM_TYPE, { signs: "+++" }, SUM_META).nInputs).toBe(3);
  });

  it("uses the registry port shapes for user blocks", () => {
    expect(getDefaultPortShapes({ id: "mx", type: USER_TYPE, params: {} }, REGISTRY)).toEqual({
      in: [[], [3]],
      out: [[]],
    });
    expect(
      getDefaultPortShapes({ id: "x", type: SUFFIX_TYPE, params: { signs: "+++" } }, REGISTRY).in,
    ).toEqual([[]]);
  });

  it("renders the display name and the port names as text", () => {
    const n = nodeOf(model([{ id: "mx", type: USER_TYPE, params: {} }]), "mx");
    const { getByTestId, queryByTestId, container } = renderNode("mx", n.data);
    expect(getByTestId("user-block-title").textContent).toBe("Mixer");
    expect(getByTestId("userblock-port-label-in-0").textContent).toBe("left");
    expect(queryByTestId("userblock-port-label-in-1")).toBeNull(); // 無名
    expect(getByTestId("userblock-port-label-out-0").textContent).toBe("mix");
    expect(queryByTestId("placeholder-label")).toBeNull();
    expect(container.querySelector("[data-user-block='user']")).not.toBeNull();
    // 組み込みの glyph (svg 内 glyph) を通らない: 面は user-block-face だけ
    expect(getByTestId("user-block-face")).toBeTruthy();
  });
});

describe("placeholders", () => {
  const conns = [
    { src: "g", src_idx: 0, dst: "p", dst_idx: 2 },
    { src: "p", src_idx: 1, dst: "g", dst_idx: 0 },
  ];
  const m = model(
    [
      { id: "g", type: GAIN_TYPE, params: {} },
      { id: "p", type: GONE_TYPE, params: { kept: 1 } },
    ],
    conns,
  );

  it("derives the port counts from the connections (wires are kept)", () => {
    const { nodes, edges } = modelToDiagram(m, REGISTRY);
    const p = nodes.find((n) => n.id === "p")!;
    expect(p.data.userBlock?.kind).toBe("placeholder");
    expect([p.data.nInputs, p.data.nOutputs]).toEqual([3, 2]);
    expect(edges).toHaveLength(2);
    // プレースホルダはポート数が分からないので超過扱いしない
    expect(edges.every((e) => e.style === DIAGRAM_EDGE_STYLE)).toBe(true);
    // entry は変えない
    expect(p.data.params).toEqual({ kept: 1 });
  });

  it("is not decided before the registry is loaded", () => {
    const { nodes } = modelToDiagram(m, undefined);
    expect(nodes.find((n) => n.id === "p")!.data.userBlock).toBeUndefined();
  });

  it("keeps the shape of the last seen metadata after the type disappears", () => {
    const seen = meta({
      type_path: GONE_TYPE,
      display_name: "Gone",
      source: "workspace",
      default_n_inputs: 4,
      default_n_outputs: 1,
      input_names: ["a", "b", "c", "d"],
    });
    const p = nodeOf(m, "p", REGISTRY, new Map([[GONE_TYPE, seen]]));
    expect([p.data.nInputs, p.data.nOutputs]).toEqual([4, 2]);
    const { getByTestId } = renderNode("p", p.data);
    expect(getByTestId("placeholder-label").textContent).toBe("canvas.placeholder.label");
    expect(getByTestId("user-block-title").textContent).toBe(GONE_TYPE);
    expect(getByTestId("userblock-port-label-in-3").textContent).toBe("d");
  });

  it("draws a dashed warning outline and explains in the tooltip", () => {
    const p = nodeOf(m, "p");
    const { container } = renderNode("p", p.data);
    const root = container.querySelector("[data-user-block='placeholder']");
    expect(root).not.toBeNull();
    expect(root!.getAttribute("title")).toBe("canvas.placeholder.tooltip");
    const rect = container.querySelector("svg rect");
    expect(rect!.getAttribute("stroke-dasharray")).not.toBeNull();
  });
});

describe("removed parameters and last seen metadata", () => {
  it("marks a user block that still has removed parameters (tooltip lists them)", () => {
    const n = nodeOf(
      model([{ id: "mx", type: USER_TYPE, params: { bias: 1, gone: 2 } }]),
      "mx",
    );
    expect(n.data.userBlock?.removedParams).toEqual(["bias", "gone"]);
    const { getByTestId } = renderNode("mx", n.data);
    expect(getByTestId("user-block-removed-params").getAttribute("title")).toBe(
      "canvas.removed_params",
    );
    cleanup();
    const clean = nodeOf(model([{ id: "mx", type: USER_TYPE, params: {} }]), "mx");
    const view = renderNode("mx", clean.data);
    expect(view.queryByTestId("user-block-removed-params")).toBeNull();
  });

  it("keeps the shape through the remembered metadata after a reload removed the type", () => {
    _resetLastSeenBlockMetadataForTest();
    rememberBlockMetadata([USER_META, GAIN_META]); // 再読み込み前の registry
    const after = indexRegistry([GAIN_META]); // 再読み込みで USER_TYPE が消えた
    const m = model([{ id: "mx", type: USER_TYPE, params: {} }]);
    const before = nodeOf(m, "mx");
    const n = modelToDiagram(m, after, { lastSeen: lastSeenBlockMetadata() }).nodes[0]!;
    expect(n.data.userBlock?.kind).toBe("placeholder");
    expect([n.data.nInputs, n.data.nOutputs]).toEqual([2, 1]);
    expect(n.height).toBe(before.height);
    _resetLastSeenBlockMetadataForTest();
  });
});

describe("excess ports", () => {
  const m = model(
    [
      { id: "g", type: GAIN_TYPE, params: {} },
      { id: "w", type: SINK_TYPE, params: {} },
    ],
    [
      { src: "g", src_idx: 0, dst: "w", dst_idx: 0 },
      { src: "g", src_idx: 0, dst: "w", dst_idx: 2 },
    ],
  );

  it("draws max(registry, connected) ports and marks the wires beyond the registry", () => {
    const { nodes, edges } = modelToDiagram(m, REGISTRY);
    const w = nodes.find((n) => n.id === "w")!;
    expect(w.data.nInputs).toBe(3);
    expect(w.data.userBlock?.declaredInputs).toBe(1);
    expect(edges[0]!.style).toBe(DIAGRAM_EDGE_STYLE);
    expect(edges[1]!.style).toBe(DIAGRAM_EDGE_STYLE_ERROR);
    expect(edges[1]!.data).toEqual({ excessPort: true });
  });

  it("marks the excess handles on the node", () => {
    const w = nodeOf(m, "w");
    const { container } = renderNode("w", w.data);
    const excess = container.querySelectorAll("[data-excess-port='true']");
    expect(excess).toHaveLength(2); // in[1], in[2]
  });
});

describe("pruning on parameter edits", () => {
  it("is disabled for user blocks and placeholders", () => {
    expect(canPruneOnParamChange(USER_TYPE, {}, REGISTRY)).toBe(false);
    expect(canPruneOnParamChange(SUFFIX_TYPE, { signs: "+" }, REGISTRY)).toBe(false);
    expect(canPruneOnParamChange(GONE_TYPE, {}, REGISTRY)).toBe(false);
  });

  it("stays enabled for builtin blocks", () => {
    expect(canPruneOnParamChange(SUM_TYPE, { signs: "+" }, REGISTRY)).toBe(true);
    expect(canPruneOnParamChange(SUM_TYPE, { signs: "+" })).toBe(true);
  });
});
