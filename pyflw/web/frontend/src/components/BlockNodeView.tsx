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

import {
  formatMatrixSize,
  formatNumber,
  formatPolynomial,
  formatTransferFunction,
  switchOpForCriterion,
} from "../lib/blockFormatting";
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
  // v0.33.0: per-block color 撤廃。slate-600 固定 (全カテゴリ統一)。
  const color = "#475569";
  // v0.15.0: Simulink "Flip Block" 相当の左右反転。SVG ShapeOutline のみ
  // scaleX(-1) で鏡像化 (= 三角形 ▶→◀)。Handle は flipPosition で position prop
  // 反転 (= chevron 向きと data-handlepos が反転して edge anchor が追従)。
  // ShapeContent (テキスト) は反転せず、flipped を渡して justify を切り替えて
  // 「底辺寄り」を維持。z-order は SVG → ShapeContent → Handles で drag 可能。
  const flipped = (data.flipped as boolean | undefined) ?? false;
  // Simulink 風: 接続済みのポートでは chevron ``>`` を抑制 (= edge 矢印 head と
  // 二重表示を回避)。``diagramConverter`` が edges から populate する。
  const connectedInputs = new Set<number>(
    (data.connectedInputs as number[] | undefined) ?? [],
  );
  const connectedOutputs = new Set<number>(
    (data.connectedOutputs as number[] | undefined) ?? [],
  );
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
    // v0.15.0: ``flipped`` 変化でも handle position が反転 (Position.Left ↔
    // Right) するため、React Flow の内部キャッシュを再 measure する必要あり。
  }, [id, nIn, nOut, flipped, updateNodeInternals]);

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
        minWidth={minWidthForKind(baseShape.kind)}
        minHeight={minHeightForKind(baseShape.kind)}
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
      {/* v0.15.0 Flip Block:
          - SVG ShapeOutline のみ scaleX(-1) で鏡像化 (= 三角形 ▶→◀)
          - Handle は flipPosition で position prop 反転 (= data-handlepos
            "left"↔"right" → React Flow の edge anchor が反転後の位置に追従、
            chevron も chevronStyleFor が反転 position を受けて `>`→`<`)
          - ShapeContent は反転させず flipped を受けて justify を切り替え
          z-order は元の SVG → ShapeContent → Handles を維持 (= ShapeContent が
          Handle を覆って drag を吸収するバグを回避)。 */}
      <div
        className="relative h-full w-full"
        style={{ width: shape.width, height: shape.height }}
      >
        <div
          style={{
            position: "absolute",
            inset: 0,
            transform: flipped ? "scaleX(-1)" : undefined,
          }}
        >
          <ShapeOutline shape={shape} selected={selected ?? false} />
        </div>
        <ShapeContent
          shape={shape}
          typePath={data.blockType}
          blockId={id}
          color={color}
          param={param}
          paramsRaw={(data.params as Record<string, unknown>) ?? {}}
          flipped={flipped}
        />
        {Array.from({ length: nIn }, (_, i) => {
          const pos = inputHandlePosition(shape, i, nIn);
          const finalPos = flipped ? flipPosition(pos.position) : pos.position;
          const showChevron = !connectedInputs.has(i);
          return (
            <Handle
              key={`in-${i}`}
              type="target"
              position={finalPos}
              id={String(i)}
              style={arrowHandleStyle(pos.topPct)}
            >
              {showChevron && <span style={chevronStyleFor(finalPos, flipped)} />}
            </Handle>
          );
        })}
        {Array.from({ length: nOut }, (_, i) => {
          const pos = outputHandlePosition(shape, i, nOut);
          const finalPos = flipped ? flipPosition(pos.position) : pos.position;
          const showChevron = !connectedOutputs.has(i);
          return (
            <Handle
              key={`out-${i}`}
              type="source"
              position={finalPos}
              id={String(i)}
              style={arrowHandleStyle(pos.topPct)}
            >
              {showChevron && <span style={chevronStyleFor(finalPos, flipped)} />}
            </Handle>
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
  selected,
}: {
  shape: BlockShape;
  selected: boolean;
}): JSX.Element {
  const { width: w, height: h, kind } = shape;
  // Simulink 風: 細黒線 + 白背景 + フラット (drop-shadow なし)。selected は薄青、
  // container だけ僅かに色を変える程度で、通常時は完全モノトーン。
  const stroke = selected ? "#2563eb" : "#1e293b";
  // Simulink 風: 通常も Subsystem も白背景、container 識別は二重枠で行う
  const fill = "white";
  const strokeWidth = selected ? 1.5 : 1;

  const commonProps = {
    fill,
    stroke,
    strokeWidth,
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
        // Simulink 風: 角丸なし、塗り潰しは細い黒バー
        <rect
          x={1}
          y={1}
          width={w - 2}
          height={h - 2}
          {...commonProps}
          fill="#1e293b"
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
        // Simulink 風: 角丸なし。Subsystem も他のブロックと同じ単枠
        // (= ユーザー要望、二重枠は廃止)。
        <rect x={1} y={1} width={w - 2} height={h - 2} {...commonProps} />
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
  paramsRaw,
  flipped = false,
}: {
  shape: BlockShape;
  typePath: string;
  blockId: string;
  color: string;
  param: string | null;
  paramsRaw: Record<string, unknown>;
  flipped?: boolean;
}): JSX.Element {
  const { kind } = shape;

  // 三角形 (Gain): 底辺側に param (k=...) を表示。flipped=false なら底辺=左→
  // 左寄せ + pl-2.5、flipped=true なら底辺=右→右寄せ + pr-2.5。テキスト自身は
  // どちらでも左→右で読める向きのまま (= scaleX 反転しない)。
  if (kind === "triangle-r") {
    const align = flipped
      ? "justify-end pr-2.5 pl-3"
      : "justify-start pl-2.5 pr-3";
    return (
      <div
        className={`absolute inset-0 flex items-center text-[10px] font-mono font-semibold tabular-nums text-slate-800 ${align}`}
      >
        <span className="truncate">{param ?? "k"}</span>
      </div>
    );
  }

  // 円 (Sum, Product, Divide): 中央に × / ÷、Sum は per-port signs 表示 (v0.35.3)。
  if (kind === "circle") {
    // v0.35.3: Sum は Add と同じく **各入力ポート位置に signs を表示**。
    // 旧版は signs 文字列 ("+-+" 等) を中央 1 か所にベタっと表示していた。
    if (typePath.endsWith(".Sum")) {
      const signs =
        typeof (paramsRaw as Record<string, unknown>).signs === "string"
          ? ((paramsRaw as Record<string, unknown>).signs as string)
          : "++";
      const n = signs.length;
      return (
        <div className="pointer-events-none absolute inset-0">
          {Array.from(signs).map((s, i) => (
            <span
              key={i}
              className="absolute -translate-y-1/2 font-mono text-[10px] font-bold leading-none text-slate-800"
              style={{
                top: `${((i + 1) * 100) / (n + 1)}%`,
                // 円の輪郭の内側、左寄せ (= ポート chevron の真横)
                left: "22%",
              }}
            >
              {s === "-" ? "−" : "+"}
            </span>
          ))}
        </div>
      );
    }
    let symbol = "";
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

  // 台形 (Inport / Outport): Simulink 風にポート番号 (= port_idx + 1) を表示。
  if (kind === "trapezoid-r" || kind === "trapezoid-l") {
    const portIdx =
      typeof (paramsRaw as Record<string, unknown>).port_idx === "number"
        ? ((paramsRaw as Record<string, unknown>).port_idx as number)
        : 0;
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[12px] font-semibold text-slate-800">
        <span>{portIdx + 1}</span>
      </div>
    );
  }

  // rect-wide (TransferFunction 等): Simulink 風に **実際の式** を 2 行表示する。
  // Display は live 値、TransferFunction / DiscreteTransferFunction は num/den 多項式、
  // StateSpace 系は (A,B,C,D) 行列サイズ、それ以外は glyph を維持。
  if (kind === "rect-wide") {
    if (typePath.endsWith(".Display")) {
      return <DisplayLiveValue blockId={blockId} />;
    }
    if (
      typePath.endsWith(".TransferFunction") ||
      typePath.endsWith(".DiscreteTransferFunction")
    ) {
      const variable = typePath.endsWith(".DiscreteTransferFunction") ? "z" : "s";
      const params = paramsRaw as Record<string, unknown>;
      const tf = formatTransferFunction(params.numerator, params.denominator, variable);
      return <TransferFunctionFraction num={tf.num} den={tf.den} />;
    }
    if (typePath.endsWith(".MimoTransferFunction")) {
      const params = paramsRaw as Record<string, unknown>;
      // numerators は 3D (= [outputs][inputs][order])、行列形式で先頭要素のみ表示
      const num = Array.isArray(params.numerators)
        ? Array.isArray((params.numerators as unknown[])[0]) &&
          Array.isArray(((params.numerators as unknown[][])[0])[0])
          ? formatPolynomial(
              ((params.numerators as unknown[][][])[0])[0],
              "s",
            )
          : "..."
        : "?";
      const den = formatPolynomial(params.denominator, "s");
      return <TransferFunctionFraction num={`[${num}, ...]`} den={den} />;
    }
    if (
      typePath.endsWith(".StateSpace") ||
      typePath.endsWith(".DiscreteStateSpace")
    ) {
      const params = paramsRaw as Record<string, unknown>;
      const sizeA = formatMatrixSize(params.A);
      return (
        <div className="absolute inset-0 flex flex-col items-center justify-center font-mono text-[10px] leading-tight text-slate-800">
          <span>x' = Ax+Bu</span>
          <span className="text-[8px] text-slate-500">A: {sizeA}</span>
        </div>
      );
    }
    if (typePath.endsWith(".DiscreteIntegrator")) {
      // Ts/(z-1) (Forward Euler の標準形)
      return <TransferFunctionFraction num="Ts" den="z-1" />;
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

  // Subsystem / TriggeredSubsystem: 二重枠で identification 済なので中央は空。
  // block id は外側下部のラベルに任せる (Simulink 互換、glyph 過剰を避ける)。
  if (
    typePath.endsWith(".Subsystem") ||
    typePath.endsWith(".TriggeredSubsystem")
  ) {
    return <></>;
  }

  // rect (default): Simulink 風の専用 render を type ごとに優先する
  //   - Constant: 値そのものを大きく表示 (= "1.0", "70" 等)
  //   - Integrator: ``1/s``
  //   - UnitDelay: ``1/z``
  //   - ZeroOrderHoldDirect: 階段保持アイコン (= 既存 glyph)
  //   - Derivative: ``s`` (= du/dt)
  //   - param がある (Step, Sine, ...) → 左 glyph 小 + 右 param
  //   - param がない (Abs, Sign, ...) → glyph 大、中央
  if (typePath.endsWith(".Constant")) {
    const value = (paramsRaw as Record<string, unknown>).value;
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[12px] font-semibold tabular-nums text-slate-800">
        <span className="truncate px-1">{formatNumber(value)}</span>
      </div>
    );
  }
  if (typePath.endsWith(".Integrator")) {
    return <TransferFunctionFraction num="1" den="s" />;
  }
  if (typePath.endsWith(".UnitDelay")) {
    return <TransferFunctionFraction num="1" den="z" />;
  }
  if (typePath.endsWith(".Derivative")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[14px] font-medium italic text-slate-800">
        <span>s</span>
      </div>
    );
  }
  // Abs: Simulink 風に ``|u|`` テキスト
  if (typePath.endsWith(".Abs")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[13px] font-medium italic text-slate-800">
        <span>|u|</span>
      </div>
    );
  }
  // MinMax: param.operator ("min" / "max") をそのままテキスト表示
  // (= pyflw 側の MinMax の param 名は ``operator`` であって ``function`` ではない)
  if (typePath.endsWith(".MinMax")) {
    const op = (paramsRaw as Record<string, unknown>).operator;
    const label = op === "max" ? "max" : "min";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>{label}</span>
      </div>
    );
  }
  // Switch: criterion を Simulink 風の比較式 (例 ``u2 ≥ T``) に整形
  if (typePath.endsWith(".Switch")) {
    const criterion = (paramsRaw as Record<string, unknown>).criterion;
    const op = switchOpForCriterion(criterion);
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[10px] font-medium text-slate-800">
        <span>{op}</span>
      </div>
    );
  }
  // Sign: Simulink 風に ``sign`` テキスト
  if (typePath.endsWith(".Sign")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium italic text-slate-800">
        <span>sign</span>
      </div>
    );
  }
  // v0.35.2: Add: Simulink 流に **各入力ポート位置に signs を表示**。
  // signs="++" なら + + / "+-" なら + - 等。入力ポートの y 位置は
  // ``inputHandlePosition`` と同じ ``(i+1)/(n+1)`` 等分配で揃える。
  if (typePath.endsWith(".Add")) {
    const signs =
      typeof (paramsRaw as Record<string, unknown>).signs === "string"
        ? ((paramsRaw as Record<string, unknown>).signs as string)
        : "++";
    const n = signs.length;
    return (
      <div className="pointer-events-none absolute inset-0">
        {Array.from(signs).map((s, i) => (
          <span
            key={i}
            className="absolute left-1 -translate-y-1/2 font-mono text-[12px] font-bold leading-none text-slate-800"
            style={{ top: `${((i + 1) * 100) / (n + 1)}%` }}
          >
            {s === "-" ? "−" : "+"}
          </span>
        ))}
      </div>
    );
  }

  // Logical / Relational: param.operator をそのまま中央表示
  if (
    typePath.endsWith(".LogicalOperator") ||
    typePath.endsWith(".RelationalOperator")
  ) {
    const op = (paramsRaw as Record<string, unknown>).operator;
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-semibold text-slate-800">
        <span>{typeof op === "string" ? op : "?"}</span>
      </div>
    );
  }

  // それ以外の rect: Simulink 風に **glyph を中央大きく** 配置 (param 値の併記は
  // しない、Simulink も icon only)。param 値はパラメータパネルで見る。
  return (
    <div
      className="absolute inset-0 flex items-center justify-center px-1.5"
      style={{ color }}
    >
      <div className="h-[70%] w-[80%]">
        <BlockGlyph typePath={typePath} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// NodeResizer の最小サイズを shape kind ごとに調整する。default (40×28) では
// bar (Mux/Demux: base 18×64) が「base 幅 < min 幅」で強制拡大されてリサイズ
// 不可になっていた (ユーザー報告)。各 shape の自然な最小値に合わせる。
// ---------------------------------------------------------------------------

function minWidthForKind(kind: BlockShape["kind"]): number {
  switch (kind) {
    case "bar":
      return 4; // Mux/Demux は Simulink 風の細い black bar、最低限の視認性のみ確保
    case "circle":
      return 28;
    case "triangle-r":
      return 32;
    case "trapezoid-r":
    case "trapezoid-l":
      return 36;
    case "rect-wide":
      return 56;
    default:
      return 40; // 一般 rect の従来値
  }
}

function minHeightForKind(kind: BlockShape["kind"]): number {
  switch (kind) {
    case "bar":
      return 24; // 縦長前提だが極端に小さくはしない
    case "circle":
      return 28;
    default:
      return 28;
  }
}

// ---------------------------------------------------------------------------
// Handle / Chevron styling: React Flow デフォルト挙動を尊重 (transform 上書き
// すると anchor 認識が壊れて drag できなくなる)。Handle 中心 = ブロック境界線上
// で chevron も同じ位置。矢印 head のサイズは 8×8 で refX 補正分の隙間を最小化
// する妥協ラインとして残す。完全ゼロを目指すには Custom Edge Component で path
// 終端を内側に手動調整する必要があるが、規模が大きいので将来検討。
// ---------------------------------------------------------------------------

function arrowHandleStyle(topPct: number): React.CSSProperties {
  // v0.20.4: Handle を 24×24 に拡大して chevron ``>`` (= Handle 中心から外側
  // +6〜+12 px の位置) を hit area に含める。
  //
  // v0.20.9: v0.20.8 で transform を override して Handle center を node 境界
  // にロックしようとしたが、Handle が node 内側 24 px に押し込まれて chevron
  // がブロック内に表示される問題発生 (ユーザー指摘「ポート位置を変更するな」)
  // → React Flow デフォルト transform に戻して chevron は node 外側のままに。
  // edge と node の隙間は React Flow デフォルト挙動 (Handle center が node
  // 境界の少し外側) と markerEnd 削除 (v0.20.7) で当面我慢する。
  return {
    top: `${topPct}%`,
    background: "transparent",
    width: 24,
    height: 24,
    border: "none",
    borderRadius: 0,
  };
}

const CHEVRON_STYLE: React.CSSProperties = {
  position: "absolute",
  top: "50%",
  left: "50%",
  width: 6,
  height: 6,
  borderTop: "1.75px solid #475569",
  borderRight: "1.75px solid #475569",
  // ``translate`` で中央寄せしてから ``rotate`` で 45deg 倒す = 上 + 右辺が
  // 「左下→右中央→左上」の chevron になる (= ``>``)。
  transform: "translate(-50%, -50%) rotate(45deg)",
  pointerEvents: "none",
};

/**
 * 全 shape 共通: chevron ``>`` を Handle 中心 (= ブロック境界線上) からさらに
 * 1 chevron 分 (= 6px) **外側** に押し出す。input (Position.Left) は左へ、output
 * (Position.Right) は右へ。これによりブロック種別 (rect / bar / circle / triangle
 * 等) に関わらず chevron 位置が統一され、Simulink の見た目に揃う。
 */
/**
 * v0.15.0: 左右反転 (= ``data.flipped``) 用に Position を反転する。
 * Position.Left ↔ Position.Right、Top/Bottom は不変。
 */
function flipPosition(p: Position): Position {
  if (p === Position.Left) return Position.Right;
  if (p === Position.Right) return Position.Left;
  return p;
}

function chevronStyleFor(
  position: Position,
  flipped: boolean,
): React.CSSProperties {
  // 反転時はブロックの信号フローが右→左になるので chevron も ``>`` → ``<``。
  // borderTop+borderRight の corner を rotate(45deg) で ``>`` に、(-135deg) で ``<`` に。
  const rot = flipped ? "rotate(-135deg)" : "rotate(45deg)";
  if (position === Position.Left) {
    return {
      ...CHEVRON_STYLE,
      transform: `translate(-150%, -50%) ${rot}`,
    };
  }
  if (position === Position.Right) {
    return {
      ...CHEVRON_STYLE,
      transform: `translate(50%, -50%) ${rot}`,
    };
  }
  return CHEVRON_STYLE;
}

// ---------------------------------------------------------------------------
// Simulink 風: 分数形式で num / den を 2 行表示する小さな helper component。
// TransferFunction / DiscreteTransferFunction / Integrator (1/s) / UnitDelay
// (1/z) / DiscreteIntegrator (Ts/(z-1)) で共通利用する。
// ---------------------------------------------------------------------------

function TransferFunctionFraction({
  num,
  den,
}: {
  num: string;
  den: string;
}): JSX.Element {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center px-1 font-mono text-[11px] leading-tight text-slate-800">
      <span className="truncate">{num}</span>
      <div className="my-[1px] h-[1px] w-[80%] bg-slate-800" />
      <span className="truncate">{den}</span>
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
  // NOTE (v0.15.0 / code-reviewer SHOULD): v0.15.0 で ShapeContent は ``paramsRaw``
  // を直接参照する個別 branch (= Constant 値 / Switch / Logical / Relational /
  // UnitDelay / DiscreteIntegrator / ZeroOrderHoldDirect 等) で render する形に
  // 移行した。本関数の戻り値は現在 **Gain (= k=...) と Sum (= signs)** にしか
  // 使われていない (= triangle-r / circle 専用)。残りの分岐は dead code 候補。
  // 将来 (v0.16.0+) で整理する想定で、いまは残しておく (drag/drop 経由の互換性)。
  const t = data.blockType;
  const p = data.params;
  if (t.endsWith(".Constant")) return formatScalar(p.value); // ← dead: ShapeContent.Constant が直接 render
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
    // ← dead: UnitDelay / DiscreteIntegrator は ShapeContent で TransferFunctionFraction、
    //   ZeroOrderHoldDirect は glyph 中央配置に移行
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
    // ← dead: ShapeContent.Switch が switchOpForCriterion で直接 render
    const c = typeof p.criterion === "string" ? p.criterion : ">=";
    return `${c}${formatScalar(p.threshold)}`;
  }
  if (t.endsWith(".RelationalOperator") || t.endsWith(".LogicalOperator")) {
    // ← dead: ShapeContent が paramsRaw.operator を直接 render
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
