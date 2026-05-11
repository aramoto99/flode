// v0.26.0: Simulink-style auto-connect-on-edge の geometry 判定テスト。

import { describe, expect, it } from "vitest";

import {
  type BlockGeom,
  type EdgeGeom,
  blockOnEdge,
  blockSISOPorts,
  findSpliceCandidate,
} from "../src/lib/autoSplice";
import type { BlockMetadata } from "../src/types/api";

// Gain ブロックの BlockMetadata stub (n_inputs=1, n_outputs=1 を default に)
const GAIN_META: BlockMetadata = {
  type_path: "pyflw.blocks.mathops.Gain",
  display_name: "Gain",
  category: "Math Operations",
  icon: "",
  color: "",
  docstring_summary: "",
  params_spec: [],
  default_n_inputs: 1,
  default_n_outputs: 1,
  port_shapes_in_default: [],
  port_shapes_out_default: [],
  tags: [],
  is_container: false,
  mask_capable: false,
};

const CONSTANT_META: BlockMetadata = {
  ...GAIN_META,
  type_path: "pyflw.blocks.sources.Constant",
  default_n_inputs: 0,
  default_n_outputs: 1,
};

const SCOPE_META: BlockMetadata = {
  ...GAIN_META,
  type_path: "pyflw.blocks.sinks.Scope",
  default_n_inputs: 1,
  default_n_outputs: 0,
};

const SUM_META: BlockMetadata = {
  ...GAIN_META,
  type_path: "pyflw.blocks.mathops.Sum",
  default_n_inputs: 2,
  default_n_outputs: 1,
};

function makeRegistry(): Map<string, BlockMetadata> {
  return new Map<string, BlockMetadata>([
    [GAIN_META.type_path, GAIN_META],
    [CONSTANT_META.type_path, CONSTANT_META],
    [SCOPE_META.type_path, SCOPE_META],
    [SUM_META.type_path, SUM_META],
  ]);
}

// ---------------------------------------------------------------------------
// blockSISOPorts
// ---------------------------------------------------------------------------

describe("blockSISOPorts", () => {
  it("returns port positions for SISO block", () => {
    const block: BlockGeom = {
      id: "gain",
      type: "pyflw.blocks.mathops.Gain",
      params: {},
      x: 100,
      y: 200,
    };
    // Gain shape: triangle-r, width=60, height=50 → output at center (50%)
    // input topPct = (0+1)*100/(1+1) = 50
    const ports = blockSISOPorts(block, 1, 1);
    expect(ports).not.toBeNull();
    expect(ports!.input).toEqual({ x: 100, y: 225 }); // 200 + 50/2
    expect(ports!.output).toEqual({ x: 160, y: 225 }); // 100 + 60, 200 + 25
  });

  it("returns null for non-SISO blocks", () => {
    const sum: BlockGeom = {
      id: "sum",
      type: "pyflw.blocks.mathops.Sum",
      params: {},
      x: 100,
      y: 200,
    };
    expect(blockSISOPorts(sum, 2, 1)).toBeNull();
    expect(blockSISOPorts(sum, 1, 2)).toBeNull();
    expect(blockSISOPorts(sum, 0, 1)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// blockOnEdge — pure geometric test
// ---------------------------------------------------------------------------

describe("blockOnEdge: straight horizontal edge", () => {
  // edge: source.right (100, 50) → target.left (400, 50)
  const source = { x: 100, y: 50 };
  const target = { x: 400, y: 50 };

  it("matches block dropped on the wire (same Y)", () => {
    expect(
      blockOnEdge(
        { x: 200, y: 50 },
        { x: 260, y: 50 },
        source,
        target,
      ),
    ).toBe(true);
  });

  it("rejects block with Y offset beyond tolerance", () => {
    expect(
      blockOnEdge(
        { x: 200, y: 80 },
        { x: 260, y: 80 },
        source,
        target,
      ),
    ).toBe(false);
  });

  it("matches block with small Y offset within tolerance", () => {
    expect(
      blockOnEdge(
        { x: 200, y: 56 },
        { x: 260, y: 56 },
        source,
        target,
      ),
    ).toBe(true);
  });

  it("rejects block outside x range (left of source)", () => {
    expect(
      blockOnEdge(
        { x: 30, y: 50 },
        { x: 90, y: 50 },
        source,
        target,
      ),
    ).toBe(false);
  });

  it("rejects block outside x range (right of target)", () => {
    expect(
      blockOnEdge(
        { x: 410, y: 50 },
        { x: 470, y: 50 },
        source,
        target,
      ),
    ).toBe(false);
  });

  it("rejects block whose input port is right of output port (invalid geometry)", () => {
    expect(
      blockOnEdge(
        { x: 260, y: 50 },
        { x: 200, y: 50 },
        source,
        target,
      ),
    ).toBe(false);
  });
});

describe("blockOnEdge: stepped edge with vertical mid-segment", () => {
  // source = (100, 50), target = (400, 200) → midX = 250
  // path: (100,50) → (250,50) → (250,200) → (400,200)
  const source = { x: 100, y: 50 };
  const target = { x: 400, y: 200 };

  it("matches block on source-side horizontal (y=50)", () => {
    expect(
      blockOnEdge(
        { x: 150, y: 50 },
        { x: 210, y: 50 },
        source,
        target,
      ),
    ).toBe(true);
  });

  it("matches block on target-side horizontal (y=200)", () => {
    expect(
      blockOnEdge(
        { x: 290, y: 200 },
        { x: 350, y: 200 },
        source,
        target,
      ),
    ).toBe(true);
  });

  it("rejects block straddling source-side and target-side horizontals", () => {
    expect(
      blockOnEdge(
        { x: 150, y: 50 },
        { x: 350, y: 200 },
        source,
        target,
      ),
    ).toBe(false);
  });

  it("rejects block on vertical segment (= unsupported case)", () => {
    expect(
      blockOnEdge(
        { x: 250, y: 100 },
        { x: 250, y: 150 },
        source,
        target,
      ),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// findSpliceCandidate — integration test
// ---------------------------------------------------------------------------

describe("findSpliceCandidate", () => {
  const registry = makeRegistry();

  // 既存ダイアグラム: const_0 → scope_0 (horizontal wire)
  const constBlock: BlockGeom = {
    id: "const_0",
    type: "pyflw.blocks.sources.Constant",
    params: {},
    x: 50,
    y: 100,
  };
  const scopeBlock: BlockGeom = {
    id: "scope_0",
    type: "pyflw.blocks.sinks.Scope",
    params: { n_inputs: 1 },
    x: 400,
    y: 100,
  };
  const edge: EdgeGeom = {
    src: "const_0",
    src_idx: 0,
    dst: "scope_0",
    dst_idx: 0,
  };

  it("finds the edge when Gain dropped on the wire", () => {
    // Constant: rect default 72×40 → output (50+72, 100+20) = (122, 120)
    // Scope: rect-wide 96×44 → input (400, 100+22) = (400, 122)
    // 上記 edge は y=120 -> y=122 (= ほぼ水平)
    // Gain (triangle-r 60x50) を (200, 95) に置く → input (200, 120), output (260, 120)
    const gain: BlockGeom = {
      id: "gain_0",
      type: "pyflw.blocks.mathops.Gain",
      params: {},
      x: 200,
      y: 95,
    };
    const result = findSpliceCandidate(
      gain,
      [constBlock, scopeBlock, gain],
      [edge],
      registry,
    );
    expect(result).not.toBeNull();
    expect(result!.edge).toEqual(edge);
  });

  it("returns null when block is far from any edge", () => {
    const gain: BlockGeom = {
      id: "gain_0",
      type: "pyflw.blocks.mathops.Gain",
      params: {},
      x: 200,
      y: 500, // y が edge から大きく離れる
    };
    const result = findSpliceCandidate(
      gain,
      [constBlock, scopeBlock, gain],
      [edge],
      registry,
    );
    expect(result).toBeNull();
  });

  it("returns null for non-SISO blocks (Sum 2-in)", () => {
    const sum: BlockGeom = {
      id: "sum_0",
      type: "pyflw.blocks.mathops.Sum",
      params: { signs: "++" },
      x: 200,
      y: 95,
    };
    const result = findSpliceCandidate(
      sum,
      [constBlock, scopeBlock, sum],
      [edge],
      registry,
    );
    expect(result).toBeNull();
  });

  it("returns null when block already has connections (caller filters; helper ignores self-edges only)", () => {
    // 本 helper では self-edge (block 自身が src or dst) を除外するだけで、
    // 「block は無接続でないと splice しない」フィルタは呼び出し側 (DiagramCanvas)。
    // 本テストは self-edge の除外だけ確認する。
    const gain: BlockGeom = {
      id: "gain_0",
      type: "pyflw.blocks.mathops.Gain",
      params: {},
      x: 200,
      y: 95,
    };
    const selfEdge: EdgeGeom = {
      src: "const_0",
      src_idx: 0,
      dst: "gain_0",
      dst_idx: 0,
    };
    // self-edge のみだと candidates が 0 で null
    const result = findSpliceCandidate(
      gain,
      [constBlock, scopeBlock, gain],
      [selfEdge],
      registry,
    );
    expect(result).toBeNull();
  });

  it("returns null when multiple edges match (ambiguous)", () => {
    // 2 本の並行 edge を別の block 経由で作り、Gain が両方に乗るケース
    const const2: BlockGeom = {
      id: "const_1",
      type: "pyflw.blocks.sources.Constant",
      params: {},
      x: 50,
      y: 100, // 同じ y で並行
    };
    const scope2: BlockGeom = {
      id: "scope_1",
      type: "pyflw.blocks.sinks.Scope",
      params: { n_inputs: 1 },
      x: 400,
      y: 100,
    };
    const edge2: EdgeGeom = {
      src: "const_1",
      src_idx: 0,
      dst: "scope_1",
      dst_idx: 0,
    };
    // edge と edge2 が同位置 (= 重なる) → Gain がどちらにも乗る
    const gain: BlockGeom = {
      id: "gain_0",
      type: "pyflw.blocks.mathops.Gain",
      params: {},
      x: 200,
      y: 95,
    };
    const result = findSpliceCandidate(
      gain,
      [constBlock, scopeBlock, const2, scope2, gain],
      [edge, edge2],
      registry,
    );
    expect(result).toBeNull(); // 曖昧なので何もしない
  });
});
