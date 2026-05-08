// ADR-0019 §(2) §Open Question 2: ブロック type ごとに「外形 (shape)」を割り当てる。
// Simulink はブロックの形そのものが識別情報になるため (Gain=三角、Sum=円、等)、
// 長方形に小さいグリフを置くのではなく、外形 SVG を type 固有にする。

export type BlockShapeKind =
  | "rect"           // 一般ブロック (Constant, Step, Integrator, TF, Scope, ...)
  | "rect-wide"      // formula を載せる広めの矩形 (TransferFunction, StateSpace, MIMO)
  | "triangle-r"     // 右向き三角形 (Gain)
  | "circle"         // 円 (Sum, Product, Divide)
  | "bar"            // 縦長バー (Mux, Demux)
  | "trapezoid-r"    // 右向き台形 (Inport)
  | "trapezoid-l";   // 左向き台形 (Outport)

export interface BlockShape {
  kind: BlockShapeKind;
  /** ノード描画域の幅 (px)。React Flow の node.width に渡す。 */
  width: number;
  /** 同高さ (px)。 */
  height: number;
}

/**
 * 各 type_path → 外形。明示エントリにない type_path は default ``rect``。
 */
const SHAPE_BY_TYPE: Record<string, BlockShape> = {
  // -------- 三角形 --------
  "pyflw.blocks.mathops.Gain": { kind: "triangle-r", width: 60, height: 50 },

  // -------- 円 --------
  "pyflw.blocks.mathops.Sum":     { kind: "circle", width: 44, height: 44 },
  "pyflw.blocks.mathops.Product": { kind: "circle", width: 44, height: 44 },
  "pyflw.blocks.mathops.Divide":  { kind: "circle", width: 44, height: 44 },

  // -------- 縦長バー --------
  "pyflw.blocks.routing.Mux":   { kind: "bar", width: 18, height: 64 },
  "pyflw.blocks.routing.Demux": { kind: "bar", width: 18, height: 64 },

  // -------- 台形 --------
  "pyflw.subsystems.ports.Inport":  { kind: "trapezoid-r", width: 64, height: 38 },
  "pyflw.subsystems.ports.Outport": { kind: "trapezoid-l", width: 64, height: 38 },

  // -------- 広めの矩形 (formula 多め / 値表示) --------
  "pyflw.blocks.continuous.TransferFunction":     { kind: "rect-wide", width: 92, height: 44 },
  "pyflw.blocks.continuous.StateSpace":           { kind: "rect-wide", width: 100, height: 44 },
  "pyflw.blocks.continuous.MimoTransferFunction": { kind: "rect-wide", width: 92, height: 44 },
  "pyflw.blocks.discrete.DiscreteTransferFunction":{ kind: "rect-wide", width: 92, height: 44 },
  "pyflw.blocks.discrete.DiscreteStateSpace":     { kind: "rect-wide", width: 100, height: 44 },
  "pyflw.blocks.discrete.DiscreteIntegrator":     { kind: "rect-wide", width: 80, height: 44 },
  // -------- Display は live 数値を大きく表示するため広め --------
  "pyflw.blocks.sinks.Display":                   { kind: "rect-wide", width: 96, height: 44 },

  // 残り (Constant / Step / Sine / Ramp / Clock / PulseGenerator / Saturation / Abs /
  // Sign / MinMax / Integrator / Derivative / UnitDelay / ZeroOrderHoldDirect /
  // Logical / Relational / Switch / Scope / Terminator / Subsystem) は default rect。
};

/** デフォルト矩形のサイズ。 */
const DEFAULT_RECT: BlockShape = { kind: "rect", width: 72, height: 40 };

/**
 * type_path から shape を返す。未指定の type は default ``rect``。
 */
export function getBlockShape(typePath: string): BlockShape {
  return SHAPE_BY_TYPE[typePath] ?? DEFAULT_RECT;
}

/**
 * shape kind が既存 ``BlockShapeKind`` のどれかであることを検査する type guard。
 * テスト等で使う。
 */
export function isKnownShapeKind(s: string): s is BlockShapeKind {
  return [
    "rect",
    "rect-wide",
    "triangle-r",
    "circle",
    "bar",
    "trapezoid-r",
    "trapezoid-l",
  ].includes(s);
}
