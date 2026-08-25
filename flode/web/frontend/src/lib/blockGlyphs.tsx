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

// SPEC-0010 / ADR-0059 (v5.3.0): RandomSource glyph。サンプル時刻で hold する
// 確率的入力を「ジャギー (noise-like) な階段波」で表現。axis 省略でコンパクト。
const RandomSourceGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="3,14 6,14 6,8 9,8 9,17 12,17 12,11 15,11 15,6 18,6 18,15 21,15" />
  </svg>
);

// =============================================================================
// Math
// =============================================================================

// v0.33.3: 旧版は 15% opacity の塗りつぶしで「再生ボタン ▶」感が出ていた
// (ユーザー指摘)。リファレンスツールの Gain と整合する **輪郭線のみ** に変更。
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
// 指摘)。「+」記号のみでリファレンスツールの Add ブロック内表示と整合。
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

// リファレンスツールの DeadZone と同じ入出力特性曲線: 左下から中央 flat、右上へ線形。
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

// SPEC-0013 / ADR-0059 (v5.6.0): Rounding。階段状の量子化ステップで「整数化」を示唆。
const RoundingGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* faint axes */}
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
    <line x1="3" y1="3" x2="3" y2="20" strokeWidth="0.6" opacity="0.4" />
    {/* 階段状の量子化波形 */}
    <polyline points="4,18 8,18 8,13 13,13 13,8 17,8 17,5 21,5" />
  </svg>
);

// =============================================================================
// Discontinuities (SPEC-0012 / ADR-0059 v5.5.0)
// =============================================================================

// RateLimiter: 急峻 step 入力 (波線) → slew-limited ramp 出力 (滑らか) の対比を
// 1 viewbox で表現。左半分は jagged な入力、右半分は傾き制限された出力。
const RateLimiterGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* faint axis */}
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
    {/* 入力 step (急峻、左半分) */}
    <polyline points="3,18 7,18 7,5 11,5" strokeWidth="1" opacity="0.5" />
    {/* 出力 ramp (slew-limited、入力 step を滑らかに追従) */}
    <polyline points="11,18 14,12 17,8 21,5" />
  </svg>
);

// Relay: ヒステリシス入出力特性 (input-output curve、閉じた矩形ループ)。
// 実線 = OFF→ON 遷移経路 (下行き)、点線 = ON→OFF 遷移経路 (上行き)。
// 中央の矢印で時計回り方向を示唆。
const RelayGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* OFF hold (下) → ON 遷移 (右辺上昇) → ON hold (上) を実線で */}
    <polyline points="3,17 14,17 14,7 21,7" />
    {/* ON hold (上) → OFF 遷移 (左辺下降) → OFF hold (下) を破線で (戻り経路) */}
    <polyline
      points="21,7 10,7 10,17 3,17"
      strokeDasharray="2 1.2"
      opacity="0.55"
    />
    {/* 中央の矢印ヒント (時計回り = 右辺で下から上へ ON 遷移) */}
    <polyline points="12,15 14,12 16,15" strokeWidth="1" opacity="0.7" />
  </svg>
);

// =============================================================================
// Lookup Tables (SPEC-0008 / ADR-0059 v5.1.0)
// =============================================================================

// 補間カーブ + 4 ブレークポイント丸。breakpoints/table のテーブル参照と
// 区分補間を視覚化する。axis は faint で省スペース。
const LookupTable1DGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* faint axes */}
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
    <line x1="3" y1="3" x2="3" y2="20" strokeWidth="0.6" opacity="0.4" />
    {/* 3-segment polyline (区分補間) */}
    <polyline points="5,18 10,9 15,13 20,5" />
    {/* 4 breakpoint dots */}
    <circle cx="5" cy="18" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="10" cy="9" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="15" cy="13" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="20" cy="5" r="1.4" fill="currentColor" stroke="none" />
  </svg>
);

// SPEC-0017 / ADR-0064 v5.6.0: 2-D Lookup の格子 + 4 セル + 中心の補間点。
// 1-D の曲線 vs 2-D の格子で視覚的に区別する。
const LookupTable2DGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 3x3 格子 (= 2x2 cells) */}
    <line x1="5" y1="5" x2="19" y2="5" />
    <line x1="5" y1="12" x2="19" y2="12" />
    <line x1="5" y1="19" x2="19" y2="19" />
    <line x1="5" y1="5" x2="5" y2="19" />
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="19" y1="5" x2="19" y2="19" />
    {/* 中央セル内の補間点 */}
    <circle cx="14" cy="15" r="1.6" fill="currentColor" stroke="none" />
  </svg>
);

// SPEC-0018 / ADR-0068 v5.8.0: n-D Lookup の cube 透視図風。
// v0.44.1: 旧 glyph は cube 中央の塗り点が「サイコロ」に見えていた (ユーザー
// 指摘)。点を廃し、前面を 2×2 格子に変更 (= LookupTable2D の格子の立体版と
// いう family 表現で「table の次元拡張」を示唆)。
const LookupTableNDGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 前面の四角 (x-y 平面) */}
    <rect x="4" y="8" width="12" height="12" />
    {/* 背面の四角 (透視図のオフセット) */}
    <line x1="4" y1="8" x2="8" y2="4" />
    <line x1="16" y1="8" x2="20" y2="4" />
    <line x1="16" y1="20" x2="20" y2="16" />
    <line x1="8" y1="4" x2="20" y2="4" />
    <line x1="20" y1="4" x2="20" y2="16" />
    {/* 前面の 2×2 格子 (LookupTable2D の格子と同族)。外枠 (SW=1.6) より細い
        strokeWidth=1 で描き、立方体の輪郭を主・内部格子を従にして奥行き感を保つ */}
    <line x1="10" y1="8" x2="10" y2="20" strokeWidth="1" />
    <line x1="4" y1="14" x2="16" y2="14" strokeWidth="1" />
  </svg>
);

// SPEC-0019 / ADR-0067 v5.7.0: Prelookup。
// v0.44.1: 旧 glyph (縦軸 + 分岐線 + 極小テキスト k/f) は palette の 28px では
// 判読不能なノイズになっていた (ユーザー指摘)。テキストを排し、「非等間隔の
// 目盛付き breakpoint 軸 (ruler) 上で入力位置を矢印で特定する」構図に単純化
// (= index 検索という本質だけを描く)。
const PrelookupGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* breakpoint 軸 (ruler、目盛は非等間隔 = 実際の breakpoints を示唆) */}
    <line x1="3" y1="16" x2="21" y2="16" />
    <line x1="5" y1="16" x2="5" y2="20" />
    <line x1="9" y1="16" x2="9" y2="20" />
    <line x1="15" y1="16" x2="15" y2="20" />
    <line x1="20" y1="16" x2="20" y2="20" />
    {/* 入力位置を指す下向き矢印 (目盛 9–15 の区間内に着地) */}
    <line x1="12" y1="4" x2="12" y2="11" />
    <polyline points="9.8,9 12,11.5 14.2,9" />
  </svg>
);

// SPEC-0019 / ADR-0067 v5.7.0: InterpolationUsingPrelookup = (k, f) → y。
// v0.44.1: 旧 glyph (入力 2 線 + 棒グラフ風 table) は小サイズで「音量アイコン」
// 風に見えて意味が伝わらなかった (ユーザー指摘)。LookupTable1D と同じ
// 「faint 軸 + breakpoint 点」の family 表現に揃え、2 つの breakpoint 点の間の
// **補間点 (白抜き丸)** を主役にする。線分は白抜き丸と重ならないよう 2 分割。
const InterpolationUsingPrelookupGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* faint axes (LookupTable1D と同スタイル) */}
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
    <line x1="3" y1="3" x2="3" y2="20" strokeWidth="0.6" opacity="0.4" />
    {/* breakpoint 2 点を結ぶ区間 (補間点の周囲は空ける) */}
    <line x1="6" y1="16" x2="10.4" y2="12.6" />
    <line x1="14.6" y1="9.4" x2="19" y2="6" />
    <circle cx="6" cy="16" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="19" cy="6" r="1.4" fill="currentColor" stroke="none" />
    {/* 補間点 (白抜き) */}
    <circle cx="12.5" cy="11" r="2" strokeWidth="1.3" />
    {/* 補間点から軸への破線 (入力 u の位置を示唆) */}
    <line
      x1="12.5"
      y1="13.4"
      x2="12.5"
      y2="20"
      strokeWidth="0.8"
      strokeDasharray="1.5 1.2"
      opacity="0.5"
    />
  </svg>
);

// =============================================================================
// User-Defined Functions (SPEC-0009 / ADR-0059 v5.2.0)
// =============================================================================

// 斜体 ``f(t,u)``。MathFunction の ``f(u)`` と区別する (Fcn は t も参照可)。
// v0.44.1: fontSize 9 では 6 文字が viewBox 24 を超え右端の ``)`` が見切れて
// いた。fontSize 7 + textLength で幅 20 に収める。
// 注: textLength/lengthAdjust (本ファイルでは StateSpace 系と本 glyph のみ使用)
// の見た目は Chromium でのみ視覚検証済み。他エンジンは未検証。
const FcnGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="15"
      textAnchor="middle"
      fontSize="7"
      fontFamily="ui-monospace,monospace"
      fontStyle="italic"
      textLength="20"
      lengthAdjust="spacingAndGlyphs"
      fill="currentColor"
      stroke="none"
    >
      f(t,u)
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
// 視認性も向上 (リファレンスツールの Derivative ブロックも分数表示が標準)。
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

// v0.44.1: fontSize 6 では末尾 ``u`` が両行とも右端で見切れていた。
// textLength で幅 20 に収める (縮小率が軽微なので fontSize は 6 のまま)。
const StateSpaceGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fontStyle="italic"
      textLength="20"
      lengthAdjust="spacingAndGlyphs"
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
      textLength="20"
      lengthAdjust="spacingAndGlyphs"
      fill="currentColor"
      stroke="none"
    >
      y=Cx+Du
    </text>
  </svg>
);

// SPEC-0015 / ADR-0065 (v5.8.0): TransportDelay glyph。入力 step (左) →
// 時間 ``T`` だけずれた step (右) で「むだ時間」を視覚化。
const TransportDelayGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <line x1="3" y1="20" x2="21" y2="20" strokeWidth="0.6" opacity="0.4" />
    <polyline points="3,18 7,18 7,8 11,8" strokeWidth="1" opacity="0.5" />
    <polyline points="11,18 16,18 16,8 21,8" />
    <line x1="8" y1="6" x2="14" y2="6" strokeWidth="0.6" opacity="0.4" />
    <polyline points="13,5 14,6 13,7" strokeWidth="0.6" opacity="0.4" />
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

// v0.44.1: 旧 ``x[k+1]=Ax+Bu`` (12 文字) は fontSize 5 でも viewBox 24 を大幅に
// 超え、左右両端が見切れていた。離散系の次状態を表す標準表記 ``x⁺`` に短縮して
// StateSpace (``ẋ``) と同レイアウトで収める。
const DiscreteStateSpaceGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <text
      x="12"
      y="10"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fontStyle="italic"
      textLength="20"
      lengthAdjust="spacingAndGlyphs"
      fill="currentColor"
      stroke="none"
    >
      x⁺=Ax+Bu
    </text>
    <text
      x="12"
      y="18"
      textAnchor="middle"
      fontSize="6"
      fontFamily="serif"
      fontStyle="italic"
      textLength="20"
      lengthAdjust="spacingAndGlyphs"
      fill="currentColor"
      stroke="none"
    >
      y=Cx+Du
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

// v0.44.2 (ADR-0070): 旧 glyph は「≥」だったが、ライブラリ default の operator は
// "<" のため drop 直後の canvas 表示と不一致だった (v0.15.0 の glyph=canvas 原則)。
// default と同じ "<" に修正。
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
      &lt;
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

// v0.35.8: Library palette でもリファレンスツール風の物理的スイッチアームを表示
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

// SPEC-0014 / ADR-0059 (v5.7.0): MultiportSwitch glyph。selector (上左) で n 本
// から 1 本を選ぶ「スイッチセレクタ」記号。
const MultiportSwitchGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 上から selector 矢印 */}
    <line x1="12" y1="3" x2="12" y2="6" strokeWidth="1" opacity="0.6" />
    <polyline points="10,5 12,7 14,5" strokeWidth="1" opacity="0.6" />
    {/* 3 データ接点 (左) */}
    <circle cx="5" cy="7" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="5" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <circle cx="5" cy="17" r="1.4" fill="currentColor" stroke="none" />
    {/* スイッチアーム (中央 → 中接点へ倒れている) */}
    <circle cx="19" cy="12" r="1.4" fill="currentColor" stroke="none" />
    <line x1="19" y1="12" x2="5" y2="12" />
  </svg>
);

// SPEC-0014 / ADR-0059 (v5.7.0): Merge glyph。n 入力 (左複数) が 1 本 (右) に
// 合流する記号。
const MergeGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 3 入力 (左) が中央ノードに合流 */}
    <line x1="3" y1="6" x2="12" y2="12" />
    <line x1="3" y1="12" x2="12" y2="12" />
    <line x1="3" y1="18" x2="12" y2="12" />
    {/* 中央 → 右出力 */}
    <line x1="12" y1="12" x2="21" y2="12" />
    {/* 合流点 */}
    <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
  </svg>
);

// SPEC-0003 / ADR-0055: Goto/From は tag ベースの仮想配線。
// v0.46.2: canvas の輪郭 (blockShapes: tag-notch-l / trapezoid-r) と同じ五角形
// タグに統一 (glyph = canvas 原則、ADR-0070 ④ de facto 形状)。
// Goto: 左辺が凹むリボン尾の五角形 + tag。
const GotoGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="3,7 21,7 21,17 3,17 7,12" />
    <text
      x="13"
      y="14"
      textAnchor="middle"
      fontSize="6"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      A
    </text>
  </svg>
);

// From: 右辺が尖る矢印頭の五角形 + tag。
const FromGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polygon points="3,7 16,7 21,12 16,17 3,17" />
    <text
      x="10"
      y="14"
      textAnchor="middle"
      fontSize="6"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      A
    </text>
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

// v0.46.2: Inport / Outport は角丸カプセル + ポート番号 (リファレンスツールの
// de facto 形状、canvas の stadium 輪郭と同じ)。Inport は右端に出力 chevron、
// Outport は左端に入力 chevron を添えて向きを示す。
const InportGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <rect x="2" y="7" width="16" height="10" rx="5" />
    <text
      x="10"
      y="14.2"
      textAnchor="middle"
      fontSize="6.5"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      1
    </text>
    <polyline points="19,9.5 21.5,12 19,14.5" />
  </svg>
);

const OutportGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    <polyline points="2.5,9.5 5,12 2.5,14.5" />
    <rect x="6" y="7" width="16" height="10" rx="5" />
    <text
      x="14"
      y="14.2"
      textAnchor="middle"
      fontSize="6.5"
      fontFamily="ui-monospace,monospace"
      fill="currentColor"
      stroke="none"
    >
      1
    </text>
  </svg>
);

// ADR-0058 §論点 1: control block glyph。Subsystem 内部に置く境界ブロック
// (Inport / Outport と並ぶ"control"カテゴリ) の palette アイコン。
// 純線画、24×24 viewBox 中央寄せ、currentColor で外側から色制御可能。
const TriggerGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* 稲妻シルエット (Trigger を象徴) */}
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

const EnableGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg {...G_PROPS} className={className}>
    {/* "E" 形 (Enable の頭文字、horizontal bars で識別性確保) */}
    <line x1="6" y1="4" x2="6" y2="20" />
    <line x1="6" y1="4" x2="18" y2="4" />
    <line x1="6" y1="12" x2="15" y2="12" />
    <line x1="6" y1="20" x2="18" y2="20" />
  </svg>
);

// ADR-0058 §論点 1 (Subsystem 中央の indicator): 12×12 px の縮小版 SVG。
// BlockNodeView が Subsystem 中央に重ねて描画する用 (Trigger / Enable いずれかが
// 内部にあるとき、その存在をユーザーに視覚通知)。線画のみ、色は CSS 変数で外側
// から制御可能 (アクセシビリティ: 形状で識別、色弱配慮)。
const TriggerIndicatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 12 12"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.4}
    strokeLinejoin="miter"
    strokeLinecap="round"
    className={className}
  >
    <polyline points="7,1 4,6 6,6 5,11" />
  </svg>
);

const EnableIndicatorGlyph = ({ className }: GlyphProps): JSX.Element => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 12 12"
    fill="none"
    stroke="currentColor"
    strokeWidth={1.4}
    strokeLinecap="square"
    className={className}
  >
    <line x1="3" y1="2" x2="3" y2="10" />
    <line x1="3" y1="2" x2="9" y2="2" />
    <line x1="3" y1="6" x2="7" y2="6" />
    <line x1="3" y1="10" x2="9" y2="10" />
  </svg>
);

export { EnableIndicatorGlyph, TriggerIndicatorGlyph };

// =============================================================================
// Registry
// =============================================================================

const GLYPHS: Record<string, (props: GlyphProps) => JSX.Element> = {
  // sources
  "flode.blocks.sources.Constant": ConstantGlyph,
  "flode.blocks.sources.Step": StepGlyph,
  "flode.blocks.sources.Sine": SineGlyph,
  "flode.blocks.sources.Ramp": RampGlyph,
  "flode.blocks.sources.Clock": ClockGlyph,
  "flode.blocks.sources.PulseGenerator": PulseGeneratorGlyph,
  // SPEC-0010 / ADR-0059 (v5.3.0): Random / Noise source
  "flode.blocks.random_source.RandomSource": RandomSourceGlyph,
  // math
  "flode.blocks.mathops.Gain": GainGlyph,
  "flode.blocks.mathops.Sum": SumGlyph,
  "flode.blocks.mathops.Add": AddGlyph,
  "flode.blocks.mathops.Product": ProductGlyph,
  "flode.blocks.mathops.Saturation": SaturationGlyph,
  "flode.blocks.mathops.Abs": AbsGlyph,
  "flode.blocks.mathops.Sign": SignGlyph,
  "flode.blocks.mathops.MinMax": MinMaxGlyph,
  "flode.blocks.mathops.Divide": DivideGlyph,
  // SPEC-0002 / ADR-0053 (v0.36.0): Phase 2 Math 系 5 ブロック
  "flode.blocks.mathops.MathFunction": MathFunctionGlyph,
  "flode.blocks.mathops.TrigFunction": TrigFunctionGlyph,
  "flode.blocks.mathops.DeadZone": DeadZoneGlyph,
  "flode.blocks.mathops.CompareToConstant": CompareToConstantGlyph,
  "flode.blocks.mathops.CompareToZero": CompareToZeroGlyph,
  // SPEC-0013 / ADR-0059 (v5.6.0): Rounding
  "flode.blocks.rounding.Rounding": RoundingGlyph,
  // SPEC-0012 / ADR-0059 (v5.5.0): Discontinuities (Wave 2 第 1 弾)
  "flode.blocks.discontinuities.RateLimiter": RateLimiterGlyph,
  "flode.blocks.discontinuities.Relay": RelayGlyph,
  // SPEC-0008 / ADR-0059 (v5.1.0): Lookup Tables
  "flode.blocks.lookup.LookupTable1D": LookupTable1DGlyph,
  // SPEC-0017 / ADR-0064 (v5.6.0): Lookup Tables 2-D (Wave 3 第 1 弾)
  "flode.blocks.lookup.LookupTable2D": LookupTable2DGlyph,
  // SPEC-0019 / ADR-0067 (v5.7.0): Prelookup 分離型 (Wave 3 第 2 弾)
  "flode.blocks.lookup.Prelookup": PrelookupGlyph,
  "flode.blocks.lookup.InterpolationUsingPrelookup": InterpolationUsingPrelookupGlyph,
  // SPEC-0018 / ADR-0068 (v5.8.0): N-D Lookup (Wave 3 第 3 弾)
  "flode.blocks.lookup.LookupTableND": LookupTableNDGlyph,
  // SPEC-0009 / ADR-0059 (v5.2.0): User-Defined Functions
  "flode.blocks.userfunc.Fcn": FcnGlyph,
  // continuous
  "flode.blocks.continuous.Integrator": IntegratorGlyph,
  "flode.blocks.continuous.Derivative": DerivativeGlyph,
  "flode.blocks.continuous.TransferFunction": TransferFunctionGlyph,
  "flode.blocks.continuous.StateSpace": StateSpaceGlyph,
  "flode.blocks.continuous.MimoTransferFunction": MimoTransferFunctionGlyph,
  // SPEC-0015 / ADR-0065 (v5.8.0): Transport Delay
  "flode.blocks.transport_delay.TransportDelay": TransportDelayGlyph,
  // discrete
  "flode.blocks.discrete.UnitDelay": UnitDelayGlyph,
  "flode.blocks.discrete.DiscreteIntegrator": DiscreteIntegratorGlyph,
  "flode.blocks.discrete.ZeroOrderHoldDirect": ZeroOrderHoldDirectGlyph,
  "flode.blocks.discrete.RateTransition": RateTransitionGlyph,
  "flode.blocks.discrete.DiscreteStateSpace": DiscreteStateSpaceGlyph,
  "flode.blocks.discrete.DiscreteTransferFunction": DiscreteTransferFunctionGlyph,
  // logic
  "flode.blocks.logic.RelationalOperator": RelationalOperatorGlyph,
  "flode.blocks.logic.LogicalOperator": LogicalOperatorGlyph,
  // routing
  "flode.blocks.routing.Switch": SwitchGlyph,
  "flode.blocks.routing.Mux": MuxGlyph,
  "flode.blocks.routing.Demux": DemuxGlyph,
  // SPEC-0003 / ADR-0055: tag ベース仮想配線
  "flode.blocks.routing.Goto": GotoGlyph,
  "flode.blocks.routing.From": FromGlyph,
  // SPEC-0014 / ADR-0059 (v5.7.0): routing 拡張
  "flode.blocks.routing.MultiportSwitch": MultiportSwitchGlyph,
  "flode.blocks.routing.Merge": MergeGlyph,
  // sinks
  "flode.blocks.sinks.Scope": ScopeGlyph,
  "flode.blocks.sinks.Display": DisplayGlyph,
  "flode.blocks.sinks.XYGraph": XYGraphGlyph,
  "flode.blocks.sinks.Terminator": TerminatorGlyph,
  // subsystems
  "flode.subsystems.subsystem.Subsystem": SubsystemGlyph,
  "flode.subsystems.ports.Inport": InportGlyph,
  "flode.subsystems.ports.Outport": OutportGlyph,
  // ADR-0058: Subsystem behavior modifier control blocks
  "flode.subsystems.control_blocks.Trigger": TriggerGlyph,
  "flode.subsystems.control_blocks.Enable": EnableGlyph,
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
