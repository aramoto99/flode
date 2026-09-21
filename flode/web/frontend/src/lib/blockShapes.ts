// ADR-0019 §(2) §Open Question 2: ブロック type ごとに「外形 (shape)」を割り当てる。
// 業界標準ブロック線図ツールではブロックの形そのものが識別情報になるため (Gain=三角、Sum=円、等)、
// 長方形に小さいグリフを置くのではなく、外形 SVG を type 固有にする。

export type BlockShapeKind =
  | "rect"           // 一般ブロック (Constant, Step, Integrator, TF, Scope, ...)
  | "rect-wide"      // formula を載せる広めの矩形 (TransferFunction, StateSpace, MIMO)
  | "triangle-r"     // 右向き三角形 (Gain)
  | "circle"         // 円 (Sum, Product, Divide)
  | "bar"            // 縦長バー (Mux, Demux)
  | "trapezoid-r"    // 右辺が尖る五角形タグ (From: 矢印頭)
  | "trapezoid-l"    // 左辺が左向きに尖る五角形タグ (Goto: From の左右鏡像。v0.53.7 で確定)
  | "stadium";       // 角丸カプセル (Inport / Outport、v0.46.2: de facto 形状)

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
  // v0.47.0: 寸法を 8px モジュール基調に整理 (Gain 60×50 → 56×48、円 44 → 48、
  // rect-wide 96×48、Subsystem 120×64)。正方形群 (48) と並べたときの段差を無くし、
  // 配線の水平が合いやすくする。例外: 境界 / タグ系 (Inport / Outport 44×26、
  // Goto / From 72×28) は「通常ブロックより一段小さい」ことを優先し高さは 8 の倍数
  // にしない (意図的)。
  // -------- 三角形 --------
  "flode.blocks.mathops.Gain": { kind: "triangle-r", width: 56, height: 48 },

  // -------- 円 --------
  "flode.blocks.mathops.Sum":     { kind: "circle", width: 48, height: 48 },
  "flode.blocks.mathops.Product": { kind: "circle", width: 48, height: 48 },
  // v0.35.4: Divide を矩形化 (ユーザー要望)。signs ("*/") の per-port 表示が
  // 円形より矩形の方が見やすい (Add / Sum と統一)。
  "flode.blocks.mathops.Divide":  { kind: "rect", width: 48, height: 48 },

  // -------- 縦長バー (リファレンスツール風: 細い black bar) --------
  "flode.blocks.routing.Mux":   { kind: "bar", width: 6, height: 56 },
  "flode.blocks.routing.Demux": { kind: "bar", width: 6, height: 56 },

  // -------- Subsystem --------
  // v0.47.0: 96×56 → 120×64。ポートラベル常時表示 (v0.46.1) で内側に入力 /
  // 出力ラベルが並ぶため、中央の余白を確保する。縦はポート数で自動伸長
  // (diagramConverter、container はピッチ 16px)。
  "flode.subsystems.subsystem.Subsystem":      { kind: "rect", width: 120, height: 64 },

  // -------- カプセル (Inport / Outport) --------
  // v0.46.2: 台形 → 角丸カプセル + ポート番号 (リファレンスツールの de facto 形状、
  // ADR-0070 ④)。台形は信号タグ (Goto/From) 系の「尖った形」に見えるため誤読を
  // 招いていた (ユーザー指摘)。
  // v0.47.0: 56×32 → 44×26。境界ブロックは通常ブロック (48 正方形) より一段小さく
  // して「端点」であることを形の大きさでも示す (リファレンスツール同様)。
  "flode.subsystems.ports.Inport":  { kind: "stadium", width: 44, height: 26 },
  "flode.subsystems.ports.Outport": { kind: "stadium", width: 44, height: 26 },

  // -------- 広めの矩形 (formula 多め / 値表示) --------
  // v0.47.0: 92/100×44 → 96×48 (8px モジュール、正方形群と天地を揃える)
  "flode.blocks.continuous.TransferFunction":     { kind: "rect-wide", width: 96, height: 48 },
  "flode.blocks.continuous.StateSpace":           { kind: "rect-wide", width: 96, height: 48 },
  "flode.blocks.continuous.MimoTransferFunction": { kind: "rect-wide", width: 96, height: 48 },
  "flode.blocks.discrete.DiscreteTransferFunction":{ kind: "rect-wide", width: 96, height: 48 },
  "flode.blocks.discrete.DiscreteStateSpace":     { kind: "rect-wide", width: 96, height: 48 },
  "flode.blocks.discrete.DiscreteIntegrator":     { kind: "rect-wide", width: 80, height: 48 },
  // -------- Display は live 数値を大きく表示するため広め --------
  "flode.blocks.sinks.Display":                   { kind: "rect-wide", width: 96, height: 48 },

  // -------- v0.35.0: Add (Sum の矩形版) --------
  "flode.blocks.mathops.Add":                   { kind: "rect", width: 48, height: 48 },

  // -------- v0.34.0: glyph 中心ブロック = 正方形 48×48 --------
  // ユーザー要望「正四角形のほうが都合のいいブロックもある」。glyph のみで
  // 値表示が不要なシンボリックブロックを正方形化する。横長が必要な
  // Constant / Ramp / RateTransition / TransferFunction etc は除外 (= デフォ
  // ルト rect or rect-wide のまま)。
  "flode.blocks.continuous.Integrator":         { kind: "rect", width: 48, height: 48 },
  "flode.blocks.continuous.Derivative":         { kind: "rect", width: 48, height: 48 },
  "flode.blocks.discrete.UnitDelay":            { kind: "rect", width: 48, height: 48 },
  "flode.blocks.discrete.ZeroOrderHoldDirect":  { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.Abs":                   { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.Sign":                  { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.MinMax":                { kind: "rect", width: 48, height: 48 },
  // ADR-0079 Stage 3 (v0.64.0): 要素縮約 + 線形代数
  "flode.blocks.mathops.Reduce":                { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.DotProduct":            { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.MatrixMultiply":        { kind: "rect", width: 48, height: 48 },
  "flode.blocks.mathops.Saturation":            { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sources.Sine":                  { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sources.Step":                  { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sources.Clock":                 { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sources.PulseGenerator":        { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sinks.Scope":                   { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sinks.XYGraph":                 { kind: "rect", width: 48, height: 48 },
  "flode.blocks.sinks.Terminator":              { kind: "rect", width: 48, height: 48 },
  "flode.blocks.logic.RelationalOperator":      { kind: "rect", width: 48, height: 48 },
  "flode.blocks.logic.LogicalOperator":         { kind: "rect", width: 48, height: 48 },
  // v0.35.8: Switch は per-port ラベル (T / criterion / F) + 右半分の
  // スイッチアーム SVG を描き込むためやや横長に拡張。
  "flode.blocks.routing.Switch":                { kind: "rect", width: 64, height: 56 },

  // SPEC-0003 / ADR-0055: tag ベース仮想配線。中央に tag ラベル
  // (= 両方 ``[tag]``、v0.53.5 で実物準拠に統一) を表示するため横長。
  // v0.46.2: 矩形 → 五角形タグ (リファレンスツールの de facto 形状、ADR-0070
  // 優先度 5 → 4 へ昇格)。
  // v0.53.7: **ユーザー指摘 (2026-09-05「gotoだけ切り込みの方向が左右逆」) で確定**:
  // Goto = 左辺が左向きに尖る (From の左右鏡像 ⟨[tag] / [tag]▷) / From = 右辺尖り。
  // v0.53.5-6 の「左辺凹み (tag-notch-l)」は切り込みの向きが実物と逆だった。
  // 根拠はユーザーの実物照合 — 推測で再変更しないこと。
  // tag 文字列の長さに応じて NodeResizer で手動伸縮可能 (= 既存ブロックと同じ
  // 振る舞い)。SPEC-0003 §5 の tag 名上限は 64 文字。
  // GotoTagVisibility は Amendment (2026-05-19) で Phase 2 送り。
  // v0.47.0: 80×32 → 72×28 (タグ系は通常ブロックより一段小さく)
  "flode.blocks.routing.Goto":               { kind: "trapezoid-l", width: 72, height: 28 },
  "flode.blocks.routing.From":               { kind: "trapezoid-r", width: 72, height: 28 },

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
    "stadium",
  ].includes(s);
}
