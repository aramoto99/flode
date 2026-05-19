// ADR-0019 §(2) §Open Question 2: ブロック type ごとに「外形 (shape)」を割り当てる。
// 業界標準ブロック線図ツールではブロックの形そのものが識別情報になるため (Gain=三角、Sum=円、等)、
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
  // v0.35.4: Divide を矩形化 (ユーザー要望)。signs ("*/") の per-port 表示が
  // 円形より矩形の方が見やすい (Add / Sum と統一)。
  "pyflw.blocks.mathops.Divide":  { kind: "rect", width: 48, height: 48 },

  // -------- 縦長バー (リファレンスツール風: 細い black bar) --------
  "pyflw.blocks.routing.Mux":   { kind: "bar", width: 6, height: 56 },
  "pyflw.blocks.routing.Demux": { kind: "bar", width: 6, height: 56 },

  // -------- Subsystem (リファレンスツール風: 二重枠の少し大きめ rect) --------
  "pyflw.subsystems.subsystem.Subsystem":      { kind: "rect", width: 96, height: 56 },
  "pyflw.subsystems.triggered.TriggeredSubsystem": { kind: "rect", width: 96, height: 56 },

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

  // -------- v0.35.0: Add (Sum の矩形版) --------
  "pyflw.blocks.mathops.Add":                   { kind: "rect", width: 48, height: 48 },

  // -------- v0.34.0: glyph 中心ブロック = 正方形 48×48 --------
  // ユーザー要望「正四角形のほうが都合のいいブロックもある」。glyph のみで
  // 値表示が不要なシンボリックブロックを正方形化する。横長が必要な
  // Constant / Ramp / RateTransition / TransferFunction etc は除外 (= デフォ
  // ルト rect or rect-wide のまま)。
  "pyflw.blocks.continuous.Integrator":         { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.continuous.Derivative":         { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.discrete.UnitDelay":            { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.discrete.ZeroOrderHoldDirect":  { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.mathops.Abs":                   { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.mathops.Sign":                  { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.mathops.MinMax":                { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.mathops.Saturation":            { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sources.Sine":                  { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sources.Step":                  { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sources.Clock":                 { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sources.PulseGenerator":        { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sinks.Scope":                   { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sinks.XYGraph":                 { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.sinks.Terminator":              { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.logic.RelationalOperator":      { kind: "rect", width: 48, height: 48 },
  "pyflw.blocks.logic.LogicalOperator":         { kind: "rect", width: 48, height: 48 },
  // v0.35.8: Switch は per-port ラベル (T / criterion / F) + 右半分の
  // スイッチアーム SVG を描き込むためやや横長に拡張。
  "pyflw.blocks.routing.Switch":                { kind: "rect", width: 64, height: 56 },

  // SPEC-0003 / ADR-0055: tag ベース仮想配線。中央に tag ラベル
  // (= ``[tag]`` / ``>tag>`` / ``{{tag}}``) を表示するため横長の rect。
  // tag 文字列の長さに応じて NodeResizer で手動伸縮可能 (= 既存ブロックと同じ
  // 振る舞い)。SPEC-0003 §5 の tag 名上限は 64 文字。
  "pyflw.blocks.routing.Goto":               { kind: "rect", width: 80, height: 32 },
  "pyflw.blocks.routing.From":               { kind: "rect", width: 80, height: 32 },
  "pyflw.blocks.routing.GotoTagVisibility":  { kind: "rect", width: 80, height: 32 },

  // 残り (Constant / Ramp / RateTransition) は default rect (72x40) のまま、
  // 値 / icon が横長を要求するため。
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
