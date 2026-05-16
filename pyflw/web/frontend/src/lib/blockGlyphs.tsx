// ADR-0019 §(2) §Open Question 2: Block 種別ごとの SVG グリフ。
// 各 glyph は 24×24 viewBox の stateless React component。``stroke="currentColor"`` で
// registry から流し込む block color に追従。fill は内部要素のみ使用。
//
// type_path → component の dictionary。未マッピングのブロックは GlyphFallback (= 短い
// 型名のテキスト)。

import type { ReactNode } from "react";

const SW = 1.6; // 共通 stroke-width
const G_PROPS = {
  width: "100%",
  height: "100%",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: SW,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

interface GlyphProps {
  className?: string;
}

// =============================================================================
// Sources
// =============================================================================

// v0.15.0: 実機キャンバスは値そのもの (例 ``1.0``) を表示 → glyph はライブラリ
// default の ``1`` を大きく見せる (= drop 直後の挙動と一致)。
const ConstantGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="11"
      fontFamily="ui-monospace,monospace"
      fontWeight="600"
      fill="currentColor"
      stroke="none"
    >
      1
    </text>
  </svg>
);

const StepGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,18 11,18 11,7 21,7" />
  </svg>
);

const SineGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <path d="M3 12 Q 7 4, 11 12 T 19 12" />
    <line x1="3" y1="12" x2="21" y2="12" strokeWidth="0.6" opacity="0.4" />
  </svg>
);

const RampGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,20 3,18 19,4" />
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
  </svg>
);

const ClockGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <circle cx="12" cy="12" r="8" />
    <line x1="12" y1="12" x2="12" y2="6" />
    <line x1="12" y1="12" x2="16" y2="14" />
  </svg>
);

const PulseGeneratorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,18 6,18 6,8 10,8 10,18 14,18 14,8 18,8 18,18 21,18" />
  </svg>
);

// =============================================================================
// Math
// =============================================================================

// v0.33.3: 旧版は 15% opacity の塗りつぶしで「再生ボタン ▶」感が出ていた
// (ユーザー指摘)。Simulink Gain と整合する **輪郭線のみ** に変更。
const GainGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="4,4 4,20 20,12" />
  </svg>
);

const SumGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <circle cx="12" cy="12" r="8" />
    <line x1="12" y1="7" x2="12" y2="17" />
    <line x1="7" y1="12" x2="17" y2="12" />
  </svg>
);

// v0.35.0: Add (Sum の矩形版) 用 glyph。
// v0.35.1: 中央の矩形枠を削除。Diagram 上の Add ブロックは shape="rect" で
// 外枠の矩形が既に描かれており、glyph の矩形と二重表示になっていた (ユーザー
// 指摘)。「+」記号のみで Simulink の Add ブロック内表示と整合。
const AddGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="6" y1="12" x2="18" y2="12" />
    <line x1="12" y1="6" x2="12" y2="18" />
  </svg>
);

const ProductGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <circle cx="12" cy="12" r="8" />
    <line x1="8" y1="8" x2="16" y2="16" />
    <line x1="16" y1="8" x2="8" y2="16" />
  </svg>
);

const SaturationGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,18 8,18 16,6 21,6" />
    <line x1="3" y1="21" x2="21" y2="21" strokeWidth="0.6" opacity="0.3" />
    <line x1="3" y1="3" x2="3" y2="21" strokeWidth="0.6" opacity="0.3" />
  </svg>
);

// v0.15.0: 実機キャンバスはテキスト ``|u|`` 表示 → glyph も同じテキストに統一。
const AbsGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="11"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      |u|
    </text>
  </svg>
);

// v0.15.0: 実機キャンバスはテキスト ``sign`` 表示 → glyph も同じ。
const SignGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="9"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      sign
    </text>
  </svg>
);

// v0.15.0: 実機キャンバスは ``min`` / ``max`` テキスト → glyph は ``min`` (default)
// を表示しておく (ライブラリでは default state = ``min`` のため)。
const MinMaxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="9"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      min
    </text>
  </svg>
);

const DivideGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="5" y1="12" x2="19" y2="12" />
    <circle cx="12" cy="7" r="1.6" fill="currentColor" />
    <circle cx="12" cy="17" r="1.6" fill="currentColor" />
  </svg>
);

// v0.36.1: SPEC-0002 / ADR-0053 で追加した Phase 2 Math 系 5 ブロックの glyph。
// 関数名そのものではなく総称表現 (f(u) / sin の正弦波 / 入出力特性 / 比較記号) を使う
// — enum 切替時にも glyph は static なので、関数族を示唆する形に揃える。
const MathFunctionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="10"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      f(u)
    </text>
  </svg>
);

// SineGlyph と同じ正弦 1 周期だが、軸線を省略してより小型で「三角関数族」を示唆。
const TrigFunctionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <path d="M3 12 Q 7 4, 11 12 T 19 12" />
  </svg>
);

// Simulink DeadZone と同じ入出力特性曲線: 左下から中央 flat、右上へ線形。
// 中央が「不感帯」(出力 0) であることを視覚化する。
const DeadZoneGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="3" y1="12" x2="21" y2="12" strokeWidth="0.6" opacity="0.4" />
    <line x1="12" y1="3" x2="12" y2="21" strokeWidth="0.6" opacity="0.4" />
    <polyline points="3,19 10,12 14,12 21,5" />
  </svg>
);

const CompareToConstantGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="9"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      u≷c
    </text>
  </svg>
);

const CompareToZeroGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="9"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      u≷0
    </text>
  </svg>
);

// =============================================================================
// Continuous
// =============================================================================

// v0.15.0: 実機キャンバスは ``1/s`` 分数表示 → glyph も同じ。
const IntegratorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="11"
      textAnchor="middle"
      fontSize="7"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      1
    </text>
    <line x1="6" y1="13" x2="18" y2="13" strokeWidth="1" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="7"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      s
    </text>
  </svg>
);

// v0.35.6: "du/dt" は fontSize=11 だと viewBox 24 を超えて見切れていた
// (ユーザー指摘: 末尾 "t" が切れる)。分数形式 (上 "du" / 下 "dt") に変更し、
// 視認性も向上 (Simulink Derivative ブロックも分数表示が標準)。
const DerivativeGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="11"
      textAnchor="middle"
      fontSize="8"
      fontStyle="italic"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      du
    </text>
    <line x1="6" y1="12" x2="18" y2="12" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="8"
      fontStyle="italic"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      dt
    </text>
  </svg>
);

const TransferFunctionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      num(s)
    </text>
    <line x1="3" y1="12.5" x2="21" y2="12.5" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      den(s)
    </text>
  </svg>
);

const StateSpaceGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      ẋ=Ax+Bu
    </text>
    <text
      x="12"
      y="18"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      y=Cx+Du
    </text>
  </svg>
);

const MimoTransferFunctionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="5"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      [num(s)]
    </text>
    <line x1="3" y1="12.5" x2="21" y2="12.5" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      den(s)
    </text>
  </svg>
);

// =============================================================================
// Discrete
// =============================================================================

const UnitDelayGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="9"
      textAnchor="middle"
      fontSize="7"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      1
    </text>
    <line x1="6" y1="11" x2="18" y2="11" />
    <text
      x="12"
      y="19"
      textAnchor="middle"
      fontSize="8"
      fontFamily="serif"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      z
    </text>
  </svg>
);

const DiscreteIntegratorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      Ts
    </text>
    <line x1="3" y1="12.5" x2="21" y2="12.5" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      z−1
    </text>
  </svg>
);

const ZeroOrderHoldDirectGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,16 7,16 7,8 13,8 13,14 21,14" />
    <text
      x="20"
      y="22"
      textAnchor="end"
      fontSize="5"
      fill="currentColor"
      stroke="none"
    >
      ZOH
    </text>
  </svg>
);

// ADR-0036: RateTransition glyph — 2 つの異なる周期の階段波 + 矢印 (= レート変換を示唆)。
const RateTransitionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 入力側 (細かい周期) */}
    <polyline points="3,16 5,16 5,12 7,12 7,16 9,16 9,12 11,12" />
    {/* 矢印 */}
    <line x1="11" y1="14" x2="14" y2="14" />
    <polyline points="13,12 14,14 13,16" />
    {/* 出力側 (粗い周期) */}
    <polyline points="14,16 17,16 17,10 21,10" />
  </svg>
);

const DiscreteStateSpaceGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="5"
      fontFamily="serif"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      x[k+1]=Ax+Bu
    </text>
    <text
      x="12"
      y="18"
      textAnchor="middle"
      fontSize="5"
      fontFamily="serif"
      fontStyle="italic"
      fill="currentColor"
      stroke="none"
    >
      y[k]=Cx+Du
    </text>
  </svg>
);

const DiscreteTransferFunctionGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      num(z)
    </text>
    <line x1="3" y1="12.5" x2="21" y2="12.5" />
    <text
      x="12"
      y="20"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      den(z)
    </text>
  </svg>
);

// =============================================================================
// Logic
// =============================================================================

const RelationalOperatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="17"
      textAnchor="middle"
      fontSize="14"
      fontWeight="500"
      fill="currentColor"
      stroke="none"
    >
      ≥
    </text>
  </svg>
);

// v0.15.0: 実機キャンバスは operator テキスト ``AND`` / ``OR`` / ``NOT`` 等。
// ライブラリの default は ``AND`` なので glyph も同じ。
const LogicalOperatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="8"
      fontFamily="ui-monospace,monospace"
      fontWeight="600"
      fill="currentColor"
      stroke="none"
    >
      AND
    </text>
  </svg>
);

// =============================================================================
// Routing
// =============================================================================

// v0.35.8: Library palette でも Simulink 風の物理的スイッチアームを表示
// (= BlockNodeView 内の表示と整合)。2 接点 + 出力 pivot + T 側に倒れたアーム。
const SwitchGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* T 接点 (左上) */}
    <circle cx="6" cy="6" r="1.8" fill="currentColor" stroke="none" />
    {/* F 接点 (左下) */}
    <circle cx="6" cy="18" r="1.8" fill="currentColor" stroke="none" />
    {/* 出力 pivot (右中央) */}
    <circle cx="20" cy="12" r="1.8" fill="currentColor" stroke="none" />
    {/* スイッチアーム (右中央 → T 接点) */}
    <line x1="20" y1="12" x2="6" y2="6" />
  </svg>
);

// v0.15.0: 実機キャンバスは縦長 black bar (= width 6 px) なので、ライブラリ glyph
// もそれに合わせて細い縦バー + 線で「Mux はバーに集約、Demux はバーから分配」を
// 表現する。
const MuxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="11" y="3" width="2" height="18" fill="currentColor" stroke="none" />
    <line x1="3" y1="7" x2="11" y2="9" />
    <line x1="3" y1="12" x2="11" y2="12" />
    <line x1="3" y1="17" x2="11" y2="15" />
    <line x1="13" y1="12" x2="21" y2="12" />
  </svg>
);

const DemuxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="11" y="3" width="2" height="18" fill="currentColor" stroke="none" />
    <line x1="3" y1="12" x2="11" y2="12" />
    <line x1="13" y1="9" x2="21" y2="7" />
    <line x1="13" y1="12" x2="21" y2="12" />
    <line x1="13" y1="15" x2="21" y2="17" />
  </svg>
);

// =============================================================================
// Sinks
// =============================================================================

const ScopeGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="3" y="5" width="18" height="14" rx="1.5" />
    <path d="M5 14 Q 8 8, 11 14 T 17 12" strokeWidth="1.4" />
  </svg>
);

const TerminatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="4" y1="12" x2="16" y2="12" />
    <line x1="16" y1="6" x2="16" y2="18" />
    <line x1="20" y1="9" x2="20" y2="15" />
  </svg>
);

const DisplayGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* セグメント数字風の電卓ディスプレイ */}
    <rect x="3" y="6" width="18" height="12" rx="1.5" />
    <text
      x="12"
      y="15"
      textAnchor="middle"
      fontSize="7"
      fontFamily="ui-monospace,monospace"
      fontWeight="600"
      fill="currentColor"
      stroke="none"
    >
      0.00
    </text>
  </svg>
);

const XYGraphGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* x-y 軸 + 散布点 */}
    <line x1="4" y1="20" x2="20" y2="20" strokeWidth="1" opacity="0.5" />
    <line x1="4" y1="4" x2="4" y2="20" strokeWidth="1" opacity="0.5" />
    <circle cx="7" cy="16" r="1" fill="currentColor" stroke="none" />
    <circle cx="10" cy="12" r="1" fill="currentColor" stroke="none" />
    <circle cx="13" cy="9" r="1" fill="currentColor" stroke="none" />
    <circle cx="16" cy="7" r="1" fill="currentColor" stroke="none" />
    <circle cx="19" cy="6" r="1" fill="currentColor" stroke="none" />
  </svg>
);

// =============================================================================
// Subsystems
// =============================================================================

// v0.15.0: 実機キャンバスは単枠 (= 二重枠廃止) → glyph も単 rect で揃える。
const SubsystemGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="3" y="5" width="18" height="14" />
  </svg>
);

// ADR-0054: TriggeredSubsystem glyph — 雷のみ (= trigger 信号を象徴)。
// 旧 ADR-0036 版は外形 rect を含んでいたが、ShapeOutline と二重描画になるため
// 削除。BlockNodeView の中央分岐で 70% × 40% boxに描画される、24×24 viewBox 中央
// に雷を配置する。
const TriggeredSubsystemGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline
      points="14,3 9,12 13,12 10,21"
      fill="none"
      stroke="currentColor"
      strokeWidth={SW}
      strokeLinejoin="miter"
      strokeLinecap="round"
    />
  </svg>
);

const InportGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="3,6 16,6 21,12 16,18 3,18" />
    <text
      x="11"
      y="14"
      textAnchor="middle"
      fontSize="6"
      fill="currentColor"
      stroke="none"
    >
      in
    </text>
  </svg>
);

const OutportGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="3,12 8,6 21,6 21,18 8,18" />
    <text
      x="14"
      y="14"
      textAnchor="middle"
      fontSize="6"
      fill="currentColor"
      stroke="none"
    >
      out
    </text>
  </svg>
);

// =============================================================================
// Registry
// =============================================================================

const GLYPHS: Record<string, (props: GlyphProps) => JSX.Element> = {
  // sources
  "pyflw.blocks.sources.Constant": ConstantGlyph,
  "pyflw.blocks.sources.Step": StepGlyph,
  "pyflw.blocks.sources.Sine": SineGlyph,
  "pyflw.blocks.sources.Ramp": RampGlyph,
  "pyflw.blocks.sources.Clock": ClockGlyph,
  "pyflw.blocks.sources.PulseGenerator": PulseGeneratorGlyph,
  // math
  "pyflw.blocks.mathops.Gain": GainGlyph,
  "pyflw.blocks.mathops.Sum": SumGlyph,
  "pyflw.blocks.mathops.Add": AddGlyph,
  "pyflw.blocks.mathops.Product": ProductGlyph,
  "pyflw.blocks.mathops.Saturation": SaturationGlyph,
  "pyflw.blocks.mathops.Abs": AbsGlyph,
  "pyflw.blocks.mathops.Sign": SignGlyph,
  "pyflw.blocks.mathops.MinMax": MinMaxGlyph,
  "pyflw.blocks.mathops.Divide": DivideGlyph,
  // SPEC-0002 / ADR-0053 (v0.36.0): Phase 2 Math 系 5 ブロック
  "pyflw.blocks.mathops.MathFunction": MathFunctionGlyph,
  "pyflw.blocks.mathops.TrigFunction": TrigFunctionGlyph,
  "pyflw.blocks.mathops.DeadZone": DeadZoneGlyph,
  "pyflw.blocks.mathops.CompareToConstant": CompareToConstantGlyph,
  "pyflw.blocks.mathops.CompareToZero": CompareToZeroGlyph,
  // continuous
  "pyflw.blocks.continuous.Integrator": IntegratorGlyph,
  "pyflw.blocks.continuous.Derivative": DerivativeGlyph,
  "pyflw.blocks.continuous.TransferFunction": TransferFunctionGlyph,
  "pyflw.blocks.continuous.StateSpace": StateSpaceGlyph,
  "pyflw.blocks.continuous.MimoTransferFunction": MimoTransferFunctionGlyph,
  // discrete
  "pyflw.blocks.discrete.UnitDelay": UnitDelayGlyph,
  "pyflw.blocks.discrete.DiscreteIntegrator": DiscreteIntegratorGlyph,
  "pyflw.blocks.discrete.ZeroOrderHoldDirect": ZeroOrderHoldDirectGlyph,
  "pyflw.blocks.discrete.RateTransition": RateTransitionGlyph,
  "pyflw.blocks.discrete.DiscreteStateSpace": DiscreteStateSpaceGlyph,
  "pyflw.blocks.discrete.DiscreteTransferFunction": DiscreteTransferFunctionGlyph,
  // logic
  "pyflw.blocks.logic.RelationalOperator": RelationalOperatorGlyph,
  "pyflw.blocks.logic.LogicalOperator": LogicalOperatorGlyph,
  // routing
  "pyflw.blocks.routing.Switch": SwitchGlyph,
  "pyflw.blocks.routing.Mux": MuxGlyph,
  "pyflw.blocks.routing.Demux": DemuxGlyph,
  // sinks
  "pyflw.blocks.sinks.Scope": ScopeGlyph,
  "pyflw.blocks.sinks.Display": DisplayGlyph,
  "pyflw.blocks.sinks.XYGraph": XYGraphGlyph,
  "pyflw.blocks.sinks.Terminator": TerminatorGlyph,
  // subsystems
  "pyflw.subsystems.subsystem.Subsystem": SubsystemGlyph,
  "pyflw.subsystems.triggered.TriggeredSubsystem": TriggeredSubsystemGlyph,
  "pyflw.subsystems.ports.Inport": InportGlyph,
  "pyflw.subsystems.ports.Outport": OutportGlyph,
};

const GlyphFallback = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="4" y="8" width="16" height="8" rx="1" opacity="0.5" />
  </svg>
);

/**
 * type_path から glyph component を解決する。未マッピングは fallback。
 */
export function getBlockGlyph(
  typePath: string,
): (props: GlyphProps) => JSX.Element {
  return GLYPHS[typePath] ?? GlyphFallback;
}

/**
 * type_path に対応するグリフを描画する。``className`` は SVG 自身に適用される。
 */
export function BlockGlyph({
  typePath,
  className,
}: {
  typePath: string;
  className?: string;
}): ReactNode {
  const Glyph = getBlockGlyph(typePath);
  return <Glyph className={className} />;
}
