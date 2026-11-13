// ADR-0081 §論点 3 / §論点 4 (U5): ユーザーブロック・プレースホルダをモデルの上で扱う純粋関数。
// - プレースホルダ判定は registry 取得後だけ
// - 消えた引数の除去 (pruneRemovedParams) はユーザーブロックだけ、組み込み・プレースホルダは不変
// - 実行前チェックはプレースホルダ・超過ポートを Subsystem 内部まで全部集める

import { afterEach, describe, expect, it } from "vitest";

import { indexRegistry } from "../src/lib/portShapeValidate";
import {
  _resetLastSeenBlockMetadataForTest,
  collectExcessPortConnections,
  collectPlaceholderBlocks,
  collectRemovedParams,
  EXCESS_PORT_CATEGORY,
  formatRemovedParams,
  MAX_REMOVED_PARAMS_SHOWN,
  isPlaceholderType,
  lastSeenBlockMetadata,
  placeholderTypeLabel,
  PLACEHOLDER_TYPE_LABEL_CHARS,
  pruneRemovedParams,
  rememberBlockMetadata,
  removedParamNames,
  runPrecheckFailure,
  UNKNOWN_BLOCK_TYPE_CATEGORY,
} from "../src/lib/userBlockModel";
import type { BlockEntry, BlockMetadata, FlwModel } from "../src/types/api";

const USER_TYPE = "flode_ws.filters.Trim";
const GAIN_TYPE = "flode.blocks.mathops.Gain";
const SUBSYSTEM_TYPE = "flode.subsystems.subsystem.Subsystem";
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
  display_name: "Trim",
  source: "workspace",
  params_spec: [
    { name: "k", type: "float", has_default: true, default: 1.0, description: "" },
  ],
});
const GAIN_META = meta({
  params_spec: [{ name: "k", type: "float", has_default: true, default: 1, description: "" }],
});
const SUBSYSTEM_META = meta({
  type_path: SUBSYSTEM_TYPE,
  display_name: "Subsystem",
  is_container: true,
  default_n_inputs: 0,
  default_n_outputs: 0,
});
const REGISTRY = indexRegistry([USER_META, GAIN_META, SUBSYSTEM_META]);

function model(blocks: BlockEntry[], connections: FlwModel["connections"] = []): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.01, solver: "RK45", rtol: 1e-3, atol: 1e-6, dt_base: null },
    blocks,
    connections,
  };
}

afterEach(() => _resetLastSeenBlockMetadataForTest());

describe("isPlaceholderType", () => {
  it("is false before the registry is loaded (undefined or empty)", () => {
    expect(isPlaceholderType(GONE_TYPE, undefined)).toBe(false);
    expect(isPlaceholderType(GONE_TYPE, indexRegistry([]))).toBe(false);
  });

  it("is true only for types missing from a loaded registry", () => {
    expect(isPlaceholderType(GONE_TYPE, REGISTRY)).toBe(true);
    expect(isPlaceholderType(USER_TYPE, REGISTRY)).toBe(false);
    expect(isPlaceholderType(GAIN_TYPE, REGISTRY)).toBe(false);
  });
});

describe("collectRemovedParams / formatRemovedParams", () => {
  it("lists user blocks with removed parameters, including Subsystem internals", () => {
    const m = model([
      { id: "t", type: USER_TYPE, params: { k: 1, bias: 2 } },
      { id: "g", type: GAIN_TYPE, params: { k: 1, stale: 1 } },
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: {
          blocks: [{ id: "u", type: USER_TYPE, params: { x: 1, y: 2 } }],
          connections: [],
        },
      },
    ]);
    const refs = collectRemovedParams(m, REGISTRY);
    expect(refs.map((r) => [r.qualifiedId, r.params])).toEqual([
      ["t", ["bias"]],
      ["sub/u", ["x", "y"]],
    ]);
    expect(formatRemovedParams(refs)).toBe("t (bias), sub/u (x, y)");
    expect(collectRemovedParams(m, undefined)).toEqual([]);
  });

  it("limits the list and cleans the names", () => {
    const rlo = String.fromCharCode(0x202e);
    const refs = Array.from({ length: MAX_REMOVED_PARAMS_SHOWN + 2 }, (_, i) => ({
      blockId: `b${i}`,
      qualifiedId: `b${i}${rlo}`,
      type: USER_TYPE,
      params: [`p${rlo}`],
    }));
    const text = formatRemovedParams(refs);
    expect(text).not.toContain(rlo);
    expect(text.endsWith("…")).toBe(true);
    expect(text.split("(").length - 1).toBe(MAX_REMOVED_PARAMS_SHOWN);
  });
});

describe("pruneRemovedParams", () => {
  it("removes parameters that the user block no longer declares", () => {
    const m = model([{ id: "t", type: USER_TYPE, params: { k: 2, bias: 1, gone: [1] } }]);
    expect(removedParamNames(m.blocks[0]!.params, USER_META)).toEqual(["bias", "gone"]);
    const pruned = pruneRemovedParams(m, REGISTRY);
    expect(pruned.blocks[0]!.params).toEqual({ k: 2 });
    // 元のモデルは変更しない
    expect(m.blocks[0]!.params).toEqual({ k: 2, bias: 1, gone: [1] });
  });

  it("does not touch builtin blocks or placeholders", () => {
    const m = model([
      { id: "g", type: GAIN_TYPE, params: { k: 2, unknown_key: 1 } },
      { id: "p", type: GONE_TYPE, params: { anything: 1 } },
    ]);
    expect(pruneRemovedParams(m, REGISTRY)).toBe(m);
  });

  it("returns the same model when nothing is removed or the registry is not loaded", () => {
    const m = model([{ id: "t", type: USER_TYPE, params: { k: 2 } }]);
    expect(pruneRemovedParams(m, REGISTRY)).toBe(m);
    const stale = model([{ id: "t", type: USER_TYPE, params: { k: 2, bias: 1 } }]);
    expect(pruneRemovedParams(stale, undefined)).toBe(stale);
  });

  it("recurses into Subsystem blocks", () => {
    const m = model([
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: {
          blocks: [
            { id: "t", type: USER_TYPE, params: { k: 2, bias: 1 } },
            { id: "g", type: GAIN_TYPE, params: { k: 3 } },
          ],
          connections: [],
        },
      },
    ]);
    const pruned = pruneRemovedParams(m, REGISTRY);
    const inner = pruned.blocks[0]!.params.blocks as BlockEntry[];
    expect(inner[0]!.params).toEqual({ k: 2 });
    expect(inner[1]).toBe((m.blocks[0]!.params.blocks as BlockEntry[])[1]);
  });

  it("does not recurse into a user block whose parameter happens to be named blocks", () => {
    const userWithBlocks = meta({
      ...USER_META,
      params_spec: [
        { name: "blocks", type: "list", has_default: true, default: [], description: "" },
      ],
    });
    const reg = indexRegistry([userWithBlocks, GAIN_META]);
    const m = model([
      {
        id: "t",
        type: USER_TYPE,
        params: { blocks: [{ id: "x", type: USER_TYPE, params: { stale: 1 } }] },
      },
    ]);
    expect(pruneRemovedParams(m, reg)).toBe(m);
  });
});

describe("runPrecheckFailure", () => {
  const nested = model(
    [
      { id: "top", type: GONE_TYPE, params: {} },
      {
        id: "sub",
        type: SUBSYSTEM_TYPE,
        params: {
          blocks: [
            { id: "inner", type: "flode_ws.io.Old", params: {} },
            { id: "again", type: GONE_TYPE, params: {} },
          ],
          connections: [],
        },
      },
    ],
    [],
  );

  it("collects every placeholder including Subsystem internals", () => {
    expect(collectPlaceholderBlocks(nested, REGISTRY)).toEqual([
      { blockId: "top", qualifiedId: "top", type: GONE_TYPE },
      { blockId: "inner", qualifiedId: "sub/inner", type: "flode_ws.io.Old" },
      { blockId: "again", qualifiedId: "sub/again", type: GONE_TYPE },
    ]);
  });

  it("returns the same shape as the backend 400 unknown_block_type", () => {
    const f = runPrecheckFailure(nested, REGISTRY);
    expect(f).not.toBeNull();
    expect(f!.category).toBe(UNKNOWN_BLOCK_TYPE_CATEGORY);
    expect(f!.template_key).toBe("error.unknown_block_type");
    expect(f!.template_args.types).toEqual([GONE_TYPE, "flode_ws.io.Old"]);
    expect(f!.template_args.block_labels).toEqual(["top", "sub/inner", "sub/again"]);
    expect(f!.template_args.truncated).toBe(false);
    expect(f!.block_ids).toEqual(["top", "inner", "again"]);
    expect(f!.t).toBeNull();
  });

  it("reports connections beyond the registry port count of user blocks", () => {
    const m = model(
      [
        { id: "g", type: GAIN_TYPE, params: {} },
        { id: "t", type: USER_TYPE, params: {} },
        { id: "g2", type: GAIN_TYPE, params: {} },
      ],
      [
        { src: "g", src_idx: 0, dst: "t", dst_idx: 0 },
        { src: "g", src_idx: 0, dst: "t", dst_idx: 1 },
        { src: "t", src_idx: 2, dst: "g2", dst_idx: 0 },
      ],
    );
    expect(collectExcessPortConnections(m, REGISTRY).map((e) => [e.direction, e.portIndex])).toEqual([
      ["in", 1],
      ["out", 2],
    ]);
    const f = runPrecheckFailure(m, REGISTRY);
    expect(f!.category).toBe(EXCESS_PORT_CATEGORY);
    expect(f!.template_key).toBe("error.excess_port_connections");
    expect(f!.template_args.ports).toEqual(["t.in[1]", "t.out[2]"]);
    expect(f!.block_ids).toEqual(["t"]);
  });

  it("ignores builtin blocks and placeholders for excess ports", () => {
    const m = model(
      [
        { id: "g", type: GAIN_TYPE, params: {} },
        { id: "p", type: GONE_TYPE, params: {} },
      ],
      [{ src: "g", src_idx: 0, dst: "g", dst_idx: 4 }, { src: "p", src_idx: 3, dst: "g", dst_idx: 0 }],
    );
    expect(collectExcessPortConnections(m, REGISTRY)).toEqual([]);
  });

  it("passes a clean model and does not check before the registry is loaded", () => {
    const ok = model([{ id: "t", type: USER_TYPE, params: {} }]);
    expect(runPrecheckFailure(ok, REGISTRY)).toBeNull();
    expect(runPrecheckFailure(nested, undefined)).toBeNull();
  });
});

describe("placeholderTypeLabel", () => {
  it("keeps the end of long type names and strips control characters", () => {
    const rlo = String.fromCharCode(0x202e);
    expect(placeholderTypeLabel(`a.b${rlo}.C`)).toBe("a.b.C");
    const long = `flode_ws.${"x".repeat(40)}.MovingAverage`;
    const label = placeholderTypeLabel(long);
    expect(Array.from(label)).toHaveLength(PLACEHOLDER_TYPE_LABEL_CHARS);
    expect(label.startsWith("…")).toBe(true);
    expect(label.endsWith(".MovingAverage")).toBe(true);
  });
});

describe("rememberBlockMetadata", () => {
  it("keeps the last seen user block metadata after the type disappears", () => {
    rememberBlockMetadata([USER_META, GAIN_META]);
    rememberBlockMetadata([GAIN_META]); // 再読み込みで消えた
    expect(lastSeenBlockMetadata().get(USER_TYPE)).toBe(USER_META);
    // 組み込みは記憶しない (消えることが無い)
    expect(lastSeenBlockMetadata().has(GAIN_TYPE)).toBe(false);
  });
});
