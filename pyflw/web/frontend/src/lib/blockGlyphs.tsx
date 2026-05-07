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

const ConstantGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="4" y1="12" x2="20" y2="12" />
    <text
      x="12"
      y="9"
      textAnchor="middle"
      fontSize="6"
      fill="currentColor"
      stroke="none"
    >
      const
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

const GainGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="4,4 4,20 20,12" fill="currentColor" opacity="0.15" />
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

const AbsGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="4,18 12,6 20,18" />
  </svg>
);

const SignGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="3" y1="18" x2="11" y2="18" />
    <line x1="11" y1="18" x2="11" y2="6" />
    <line x1="11" y1="6" x2="21" y2="6" />
    <line x1="3" y1="12" x2="21" y2="12" strokeWidth="0.6" opacity="0.3" />
  </svg>
);

const MinMaxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="4,8 8,4 12,8" />
    <polyline points="12,16 16,20 20,16" />
  </svg>
);

const DivideGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="5" y1="12" x2="19" y2="12" />
    <circle cx="12" cy="7" r="1.6" fill="currentColor" />
    <circle cx="12" cy="17" r="1.6" fill="currentColor" />
  </svg>
);

// =============================================================================
// Continuous
// =============================================================================

const IntegratorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="14"
      fontWeight="500"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      ∫
    </text>
  </svg>
);

const DerivativeGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="16"
      textAnchor="middle"
      fontSize="11"
      fontStyle="italic"
      fontFamily="serif"
      fill="currentColor"
      stroke="none"
    >
      du/dt
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

const ZeroOrderHoldGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,18 7,18 7,12 11,12 11,8 15,8 15,14 21,14" />
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

const LogicalOperatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* AND ゲート風 */}
    <path d="M5 5 L 13 5 A 7 7 0 0 1 13 19 L 5 19 Z" />
  </svg>
);

// =============================================================================
// Routing
// =============================================================================

const SwitchGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="3" y1="6" x2="9" y2="6" />
    <line x1="3" y1="18" x2="9" y2="18" />
    <line x1="9" y1="6" x2="17" y2="10" />
    <line x1="15" y1="12" x2="21" y2="12" />
    <circle cx="9" cy="6" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="9" cy="18" r="1.4" fill="currentColor" stroke="none" />
  </svg>
);

const MuxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="9" y="3" width="3" height="18" fill="currentColor" stroke="none" rx="1" />
    <line x1="3" y1="6" x2="9" y2="9" />
    <line x1="3" y1="12" x2="9" y2="12" />
    <line x1="3" y1="18" x2="9" y2="15" />
    <line x1="12" y1="12" x2="21" y2="12" />
  </svg>
);

const DemuxGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="12" y="3" width="3" height="18" fill="currentColor" stroke="none" rx="1" />
    <line x1="3" y1="12" x2="12" y2="12" />
    <line x1="15" y1="9" x2="21" y2="6" />
    <line x1="15" y1="12" x2="21" y2="12" />
    <line x1="15" y1="15" x2="21" y2="18" />
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

const SubsystemGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="3" y="5" width="18" height="14" rx="1.5" />
    <rect x="7" y="9" width="10" height="6" rx="0.8" opacity="0.6" />
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
  "pyflw.blocks.mathops.Product": ProductGlyph,
  "pyflw.blocks.mathops.Saturation": SaturationGlyph,
  "pyflw.blocks.mathops.Abs": AbsGlyph,
  "pyflw.blocks.mathops.Sign": SignGlyph,
  "pyflw.blocks.mathops.MinMax": MinMaxGlyph,
  "pyflw.blocks.mathops.Divide": DivideGlyph,
  // continuous
  "pyflw.blocks.continuous.Integrator": IntegratorGlyph,
  "pyflw.blocks.continuous.Derivative": DerivativeGlyph,
  "pyflw.blocks.continuous.TransferFunction": TransferFunctionGlyph,
  "pyflw.blocks.continuous.StateSpace": StateSpaceGlyph,
  "pyflw.blocks.continuous.MimoTransferFunction": MimoTransferFunctionGlyph,
  // discrete
  "pyflw.blocks.discrete.UnitDelay": UnitDelayGlyph,
  "pyflw.blocks.discrete.DiscreteIntegrator": DiscreteIntegratorGlyph,
  "pyflw.blocks.discrete.ZeroOrderHold": ZeroOrderHoldGlyph,
  "pyflw.blocks.discrete.ZeroOrderHoldDirect": ZeroOrderHoldDirectGlyph,
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
