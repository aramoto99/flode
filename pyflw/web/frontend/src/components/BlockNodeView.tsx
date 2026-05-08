// ADR-0019 §(2)(3) + 視覚化リファイン: Simulink 風にブロック外形を type ごとに変える。
// - 三角 (Gain) / 円 (Sum, Product, Divide) / バー (Mux, Demux) / 台形 (Inport, Outport)
// - その他は compact rectangle (~72×40px) に固有 SVG glyph
// - 入力 = 左、出力 = 右 (Simulink 慣習)
// - block id は外形の **下** に小さく出す (Simulink もブロック名はノード下)

import {
  Handle,
  NodeResizer,
  Position,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useState } from "react";

import { BlockGlyph } from "../lib/blockGlyphs";
import {
  getBlockShape,
  type BlockShape,
  type BlockShapeKind,
} from "../lib/blockShapes";
import type { BlockNodeData } from "../lib/diagramConverter";
import { updateBlockSize, useAppStore } from "../store/appStore";

interface BlockNodeViewProps extends NodeProps {
  data: BlockNodeData;
}

export function BlockNodeView({
  data,
  selected,
  id,
}: BlockNodeViewProps): JSX.Element {
  const nIn = (data.nInputs as number | undefined) ?? 1;
  const nOut = (data.nOutputs as number | undefined) ?? 1;
  const color = (data.color as string | undefined) ?? "#475569";
  const isContainer = (data.isContainer as boolean | undefined) ?? false;
  const baseShape = getBlockShape(data.blockType);
  // diagramConverter で layout.w/h + port 数に応じて伸ばした実寸を流し込んでいる。
  // なければ base サイズ (テスト等で BlockNodeView 単独呼びの fallback)。
  const dynamicWidth = (data.shapeWidth as number | undefined) ?? baseShape.width;
  const dynamicHeight = (data.shapeHeight as number | undefined) ?? baseShape.height;

  // NodeResizer ドラッグ中の live サイズ (= プレビュー用)。onResize で逐次更新、
  // onResizeEnd で確定して store に保存 + 解除。null のときは data 駆動。
  const [liveSize, setLiveSize] = useState<{ w: number; h: number } | null>(null);
  const shape = liveSize
    ? { ...baseShape, width: liveSize.w, height: liveSize.h }
    : { ...baseShape, width: dynamicWidth, height: dynamicHeight };
  const param = summarizePrimaryParam(data);

  // React Flow v12: ハンドル数が動的に変わるノードでは、ハンドルの DOM 配置だけを
  // 変えても React Flow 内部のレジストリ (= ハンドル → ノード相対位置の cache) が
  // 古いままだと「edge を引こうとしてもハンドルが消えて見える」「描画が更新され
  // ない」状態になる。useUpdateNodeInternals(id) を呼ぶことで強制的に再 measure
  // させる。これは React Flow 公式が推奨する dynamic-handle パターン
  // (https://reactflow.dev/api-reference/hooks/use-update-node-internals)。
  const updateNodeInternals = useUpdateNodeInternals();
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, nIn, nOut, updateNodeInternals]);

  // ノード bounding box は shape のみで構成し、ID ラベルは ``absolute top: 100%`` で
  // ノードの外側に escape させる。これにより:
  //   - NodeResizer の枠線 / リサイズハンドルが shape のみを囲む (= ラベルが枠内に
  //     埋もれない)
  //   - 入出力ハンドルの相対位置が正しく shape 基準で計算される
  return (
    <div
      className="group relative"
      title={data.blockType}
      style={{ width: shape.width, height: shape.height }}
    >
      {/* React Flow NodeResizer: 選択時のみハンドル表示。
          Simulink / MATLAB ライクに、連結線は隠して **コーナー + 辺中央の小さい
          ハンドルだけ** 表示する。色も濃いスレートで地味めに、白縁取りで上品に。
          選択そのものの視覚フィードバックは ``ShapeOutline`` (= シェイプ自身の
          stroke 色を青く太らす) と CSS の subtle drop-shadow で行うので、リサイザの
          連結線は不要。

          controlled mode の都合: onResize でも updateBlockSize を呼んで store 経由で
          ラッパーをリアルタイムに追従させる (= 横方向リサイズの抜け対策)。 */}
      <NodeResizer
        isVisible={selected ?? false}
        minWidth={40}
        minHeight={28}
        lineStyle={{ borderColor: "transparent" }}
        handleStyle={{
          width: 4,
          height: 4,
          borderRadius: 0,
          background: "#0f172a",
          border: "0.5px solid white",
        }}
        onResize={(_e, params) => {
          setLiveSize({ w: params.width, h: params.height });
          updateBlockSize(id, { w: params.width, h: params.height });
        }}
        onResizeEnd={(_e, params) => {
          updateBlockSize(id, { w: params.width, h: params.height });
          setLiveSize(null);
        }}
      />
      <div
        className="relative h-full w-full"
        style={{ width: shape.width, height: shape.height }}
      >
        <ShapeOutline
          shape={shape}
          color={color}
          selected={selected ?? false}
          isContainer={isContainer}
        />
        <ShapeContent
          shape={shape}
          typePath={data.blockType}
          blockId={id}
          color={color}
          param={param}
        />
        {Array.from({ length: nIn }, (_, i) => {
          const pos = inputHandlePosition(shape, i, nIn);
          return (
            <Handle
              key={`in-${i}`}
              type="target"
              position={pos.position}
              id={String(i)}
              style={{
                top: `${pos.topPct}%`,
                background: "#475569",
                width: 7,
                height: 7,
                border: "1.5px solid white",
              }}
            />
          );
        })}
        {Array.from({ length: nOut }, (_, i) => {
          const pos = outputHandlePosition(shape, i, nOut);
          return (
            <Handle
              key={`out-${i}`}
              type="source"
              position={pos.position}
              id={String(i)}
              style={{
                top: `${pos.topPct}%`,
                background: "#475569",
                width: 7,
                height: 7,
                border: "1.5px solid white",
              }}
            />
          );
        })}
      </div>
      {/* ID ラベル: absolute で React Flow のノード境界 BOX の **下** に escape させる。
          pointer-events:none で配線 / クリック判定を妨げない。 */}
      <div
        className="pointer-events-none absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap text-center text-[10px] font-medium leading-tight text-slate-700"
      >
        {id}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outer shape (SVG path) per kind
// ---------------------------------------------------------------------------

function ShapeOutline({
  shape,
  color,
  selected,
  isContainer,
}: {
  shape: BlockShape;
  color: string;
  selected: boolean;
  isContainer: boolean;
}): JSX.Element {
  const { width: w, height: h, kind } = shape;
  const stroke = selected ? "#2563eb" : isContainer ? "#a78bfa" : "#475569";
  const fill = "white";
  const strokeWidth = selected ? 2 : isContainer ? 1.6 : 1.4;

  const dropShadow = selected
    ? "drop-shadow(0 1px 3px rgba(37,99,235,0.35))"
    : "drop-shadow(0 1px 2px rgba(15,23,42,0.08))";

  const commonProps = {
    fill,
    stroke,
    strokeWidth,
    style: { filter: dropShadow },
  };

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="absolute inset-0"
      style={{ overflow: "visible" }}
    >
      {kind === "triangle-r" && (
        <polygon points={`1,1 1,${h - 1} ${w - 1},${h / 2}`} {...commonProps} />
      )}
      {kind === "circle" && (
        // n が大きくなって h が w より大きいとき: 縦長の角丸長方形 (ピル形) に切替。
        // h <= w のとき: 通常の真円。
        h > w + 4 ? (
          <rect
            x={1}
            y={1}
            width={w - 2}
            height={h - 2}
            rx={w / 2}
            ry={w / 2}
            {...commonProps}
          />
        ) : (
          <circle cx={w / 2} cy={h / 2} r={Math.min(w, h) / 2 - 1} {...commonProps} />
        )
      )}
      {kind === "bar" && (
        <rect
          x={1}
          y={1}
          width={w - 2}
          height={h - 2}
          rx={2}
          {...commonProps}
          fill={color}
          opacity={0.85}
        />
      )}
      {kind === "trapezoid-r" && (
        <polygon
          points={`1,1 ${w - h / 2 - 1},1 ${w - 1},${h / 2} ${w - h / 2 - 1},${h - 1} 1,${h - 1}`}
          {...commonProps}
        />
      )}
      {kind === "trapezoid-l" && (
        <polygon
          points={`${h / 2 + 1},1 ${w - 1},1 ${w - 1},${h - 1} ${h / 2 + 1},${h - 1} 1,${h / 2}`}
          {...commonProps}
        />
      )}
      {(kind === "rect" || kind === "rect-wide") && (
        <rect
          x={1}
          y={1}
          width={w - 2}
          height={h - 2}
          rx={3}
          {...commonProps}
        />
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Inner content (glyph or text) per kind
// ---------------------------------------------------------------------------

function ShapeContent({
  shape,
  typePath,
  blockId,
  color,
  param,
}: {
  shape: BlockShape;
  typePath: string;
  blockId: string;
  color: string;
  param: string | null;
}): JSX.Element {
  const { kind } = shape;

  // 三角形 (Gain): 中央に param (k=...) を表示。glyph アイコンは不要 (= 三角形が
  // すでに識別情報)。
  if (kind === "triangle-r") {
    return (
      <div className="absolute inset-0 flex items-center justify-start pl-2.5 pr-3 text-[10px] font-mono font-semibold tabular-nums text-slate-800">
        <span className="truncate">{param ?? "k"}</span>
      </div>
    );
  }

  // 円 (Sum, Product, Divide): 中央に signs / × / ÷ を大きく。
  if (kind === "circle") {
    let symbol = param ?? "";
    if (typePath.endsWith(".Product")) symbol = "×";
    if (typePath.endsWith(".Divide")) symbol = "÷";
    return (
      <div className="absolute inset-0 flex items-center justify-center text-sm font-bold leading-none text-slate-800">
        <span className="truncate px-0.5">{symbol}</span>
      </div>
    );
  }

  // 縦長バー (Mux, Demux): 内部はあえて空 (= 形だけで識別、param は外で表示しない)。
  if (kind === "bar") {
    return <></>;
  }

  // 台形 (Inport / Outport): 中央に "in" / "out" 風のラベル。
  if (kind === "trapezoid-r" || kind === "trapezoid-l") {
    const label = typePath.endsWith(".Inport") ? "in" : "out";
    return (
      <div className="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-slate-700">
        <span>{label}</span>
      </div>
    );
  }

  // rect-wide (TransferFunction 等): glyph を中央いっぱいに。param は出さない (式が param)。
  // ただし Display ブロックだけは特別: WebSocket scope_batch から流れてきた最新値を
  // ブロック本体に大きく表示する。
  if (kind === "rect-wide") {
    if (typePath.endsWith(".Display")) {
      return <DisplayLiveValue blockId={blockId} />;
    }
    return (
      <div
        className="absolute inset-0 flex items-center justify-center px-1.5"
        style={{ color }}
      >
        <div className="h-[80%] w-full">
          <BlockGlyph typePath={typePath} />
        </div>
      </div>
    );
  }

  // rect (default):
  //   - param がある (Constant の値、Gain の k 等) → 左に glyph 小 + 右に値
  //   - param がない (Abs, Sign, MinMax, Clock, Integrator 等) → glyph を大きく中央配置
  if (param !== null && param !== "") {
    return (
      <div className="absolute inset-0 flex items-center gap-1 px-1.5">
        <div className="h-4 w-4 shrink-0" style={{ color }}>
          <BlockGlyph typePath={typePath} />
        </div>
        <div className="min-w-0 flex-1 truncate text-right font-mono text-[9.5px] tabular-nums text-slate-700">
          {param}
        </div>
      </div>
    );
  }
  return (
    <div
      className="absolute inset-0 flex items-center justify-center px-1.5"
      style={{ color }}
    >
      <div className="h-7 w-7">
        <BlockGlyph typePath={typePath} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Handle positioning per shape (top% within node bounds; React Flow uses
// the node's wrapper as reference)
// ---------------------------------------------------------------------------

function inputHandlePosition(
  shape: BlockShape,
  i: number,
  n: number,
): { position: Position; topPct: number } {
  // 単一入力 + 単数前提形状 (円心 1 点 / 台形)。複数あれば縦に並べる。
  // 三角形 / 円 / バー / Outport (台形-l) は全部「左辺に等間隔配置」で OK。
  if (
    shape.kind === "triangle-r" ||
    shape.kind === "circle" ||
    shape.kind === "bar" ||
    shape.kind === "trapezoid-l"
  ) {
    return { position: Position.Left, topPct: ((i + 1) * 100) / (n + 1) };
  }
  // Inport (= n_inputs=0) で稀に呼ばれた場合の安全側 fallback。
  return { position: Position.Left, topPct: ((i + 1) * 100) / (n + 1) };
}

function outputHandlePosition(
  shape: BlockShape,
  i: number,
  n: number,
): { position: Position; topPct: number } {
  // 三角形 (Gain): 出力は頂点 1 点 → 中央。複数想定なし。
  // 円 (Sum/Product/Divide): n_outputs=1 確定なので中央でよい。複数になることはない。
  // バー / 台形 / その他: 右辺に等間隔配置。
  if (shape.kind === "triangle-r" || shape.kind === "circle") {
    return { position: Position.Right, topPct: 50 };
  }
  return { position: Position.Right, topPct: ((i + 1) * 100) / (n + 1) };
}

// ---------------------------------------------------------------------------
// 主要 param サマリ (rect / triangle で使用)
// ---------------------------------------------------------------------------

function summarizePrimaryParam(data: BlockNodeData): string | null {
  const t = data.blockType;
  const p = data.params;
  if (t.endsWith(".Constant")) return formatScalar(p.value);
  if (t.endsWith(".Gain")) return `k=${formatScalar(p.k)}`;
  if (t.endsWith(".Sum")) return typeof p.signs === "string" ? p.signs : null;
  if (t.endsWith(".Step")) {
    return `${formatScalar(p.initial_value)}→${formatScalar(p.final_value)}`;
  }
  if (t.endsWith(".Sine")) return `f=${formatScalar(p.frequency)}`;
  if (t.endsWith(".Ramp")) return `slope=${formatScalar(p.slope)}`;
  if (t.endsWith(".Saturation")) {
    return `[${formatScalar(p.lower_limit)},${formatScalar(p.upper_limit)}]`;
  }
  if (
    t.endsWith(".UnitDelay") ||
    t.endsWith(".DiscreteIntegrator") ||
    t.endsWith(".ZeroOrderHoldDirect")
  ) {
    return `Ts=${formatScalar(p.sample_time)}`;
  }
  if (t.endsWith(".RateTransition")) {
    // ADR-0036: 入力 / 出力周期を併記して mode (= zoh / delay / auto) と区別する
    return `${formatScalar(p.input_sample_time)}→${formatScalar(p.output_sample_time)}`;
  }
  if (t.endsWith(".Mux") || t.endsWith(".Demux")) {
    return `n=${formatScalar(p.n)}`;
  }
  if (t.endsWith(".Switch")) {
    const c = typeof p.criterion === "string" ? p.criterion : ">=";
    return `${c}${formatScalar(p.threshold)}`;
  }
  if (t.endsWith(".RelationalOperator") || t.endsWith(".LogicalOperator")) {
    return typeof p.operator === "string" ? p.operator : null;
  }
  return null;
}

function formatScalar(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return String(v);
    if (Math.abs(v) >= 1000 || (Math.abs(v) < 0.01 && v !== 0)) {
      return v.toExponential(1);
    }
    if (Number.isInteger(v)) return String(v);
    return String(Number(v.toFixed(3)));
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "string") return v.length > 8 ? v.slice(0, 8) + "…" : v;
  if (Array.isArray(v)) return "[…]";
  return "{…}";
}

// ---------------------------------------------------------------------------
// Display block の live 値表示。WebSocket 経由で scopes store に流れてくる
// 最新サンプルをブロックフェース上に大きく描画する (Simulink Display 相当)。
// ---------------------------------------------------------------------------

/** @internal テスト用 export。プロダクション利用は BlockNodeView 経由。 */
export function DisplayLiveValue({ blockId }: { blockId: string }): JSX.Element {
  // ADR-0023: scopes[blockId] は SoA ScopeBuffer (Float64Array 列指向)。
  // 最新サンプル (= 各信号の length-1 番目の要素) を集める。
  const buffer = useAppStore((s) => s.scopes[blockId]);
  const latest =
    buffer && buffer.length > 0 && buffer.n_signals > 0
      ? buffer.values.map((col) => col[buffer.length - 1]!)
      : null;

  if (!latest || latest.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] text-slate-400">
        — — —
      </div>
    );
  }

  // 値が複数あれば縦に並べる (n_inputs > 1 の Display)
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center px-1 font-mono text-slate-900">
      {latest.map((v, i) => (
        <span
          key={i}
          className={`tabular-nums ${
            latest.length === 1
              ? "text-[14px] font-semibold leading-tight"
              : "text-[10px] leading-tight"
          }`}
        >
          {formatDisplayValue(v)}
        </span>
      ))}
    </div>
  );
}

/** @internal テスト用 export。 */
export function formatDisplayValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Math.abs(v) >= 10000 || (Math.abs(v) < 0.001 && v !== 0)) {
    return v.toExponential(2);
  }
  return v.toFixed(3);
}

// Re-export type for external consumers (referenced in App / DiagramCanvas if needed)
export type { BlockShapeKind };
