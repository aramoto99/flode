// ADR-0019 §(2)(3) + 視覚化リファイン: リファレンスツール風にブロック外形を type ごとに変える。
// - 三角 (Gain) / 円 (Sum, Product) / バー (Mux, Demux) / カプセル (Inport, Outport)
//   / 五角形タグ (Goto = 左辺が左向きに尖る = From の左右鏡像, From = 右辺尖り。v0.53.7 にユーザー指摘で確定)
// - その他は compact rectangle (~72×40px) に固有 SVG glyph
// - 入力 = 左、出力 = 右 (リファレンスツール慣習)
// - block id は外形の **下** に小さく出す (リファレンスツールもブロック名はノード下)

import {
  Handle,
  NodeResizer,
  Position,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  compareOpSymbol,
  formatMatrixSize,
  formatNumber,
  formatPolynomial,
  formatTransferFunction,
  formatValue,
} from "../lib/blockFormatting";
import {
  BlockGlyph,
  EnableIndicatorGlyph,
  TriggerEdgeGlyph,
  TriggerIndicatorGlyph,
  type TriggerEdgeMode,
} from "../lib/blockGlyphs";
import {
  getBlockShape,
  type BlockShape,
  type BlockShapeKind,
} from "../lib/blockShapes";
import {
  ENABLE_TYPE,
  getNumberParam,
  INPORT_TYPE,
  OUTPORT_TYPE,
  PYTHON_FUNCTION_TYPE,
  TRIGGER_TYPE,
} from "../lib/blockTypes";
import { dtypeForPort, useDtypeResolution } from "../lib/dtypeResolution";
import { getCachedPythonSpec } from "../lib/pythonFunctionSpec";
import type { BlockNodeData } from "../lib/diagramConverter";
import { useBlockRenameEditor } from "../lib/useBlockRename";
import type { BlockEntry } from "../types/api";
import { updateBlockSize, useAppStore } from "../store/appStore";
import { INPUT_CLS } from "./ui/inspector";

/**
 * ADR-0058 §論点 4 / §論点 11: Subsystem に含まれる control block の有無を
 * ``params.blocks`` filter で判定する。slot 順序は
 * [data_inports..., enable_slot, trigger_slot]。
 */
function resolveControlSlots(
  params: Record<string, unknown> | undefined,
): { hasTrigger: boolean; hasEnable: boolean } {
  if (!params) {
    return { hasTrigger: false, hasEnable: false };
  }
  const inner = params.blocks;
  if (!Array.isArray(inner)) {
    return { hasTrigger: false, hasEnable: false };
  }
  const hasTrigger = inner.some(
    (b) =>
      typeof b === "object" && b !== null && (b as BlockEntry).type === TRIGGER_TYPE,
  );
  const hasEnable = inner.some(
    (b) =>
      typeof b === "object" && b !== null && (b as BlockEntry).type === ENABLE_TYPE,
  );
  return { hasTrigger, hasEnable };
}

/**
 * SPEC-0022 §機能要件 7: Subsystem 外面ポートラベルの収集。
 *
 * 内部 Inport / Outport の id を `port_idx → id` のラベルとして返す。
 * 既定 id (`Inport_0` 等) も表示する (2026-08-25 Q6 撤回: リファレンスツールの
 * `In1`/`Out1` 常時表示に合わせる)。等分配の分母計算のため、data 入力ポート
 * 総数 (= Inport 件数) / 出力ポート総数も返す。slot 順序は
 * [data..., enable, trigger] (ADR-0058) で、Trigger / Enable slot はラベル対象外。
 */
interface SubsystemPortLabelInfo {
  inputs: Array<{ portIdx: number; label: string }>;
  outputs: Array<{ portIdx: number; label: string }>;
  nDataIn: number;
  nOut: number;
}

function collectSubsystemPortLabels(
  params: Record<string, unknown>,
): SubsystemPortLabelInfo {
  const out: SubsystemPortLabelInfo = {
    inputs: [],
    outputs: [],
    nDataIn: 0,
    nOut: 0,
  };
  const inner = params.blocks;
  if (!Array.isArray(inner)) return out;
  for (const raw of inner) {
    if (typeof raw !== "object" || raw === null) continue;
    const b = raw as BlockEntry;
    if (b.type !== INPORT_TYPE && b.type !== OUTPORT_TYPE) continue;
    const isInput = b.type === INPORT_TYPE;
    if (isInput) out.nDataIn += 1;
    else out.nOut += 1;
    const portIdx = getNumberParam(
      (b.params ?? {}) as Record<string, unknown>,
      "port_idx",
      -1,
    );
    if (portIdx < 0) continue;
    if (typeof b.id !== "string") continue;
    (isInput ? out.inputs : out.outputs).push({ portIdx, label: b.id });
  }
  return out;
}

/**
 * ポート脇ラベル描画 (SPEC-0022 §機能要件 7 / SPEC-0024 で一般化)。
 *
 * y 位置は handle の等分配式 (`((i+1)*100)/(n+1)`、inputHandlePosition /
 * outputHandlePosition と同じ分母) に揃える。入力=内側左寄せ / 出力=内側右寄せ、
 * flip 時は左右を入れ替える (テキスト自体は反転しない)。長いラベルは CSS 幅で
 * truncate し、`title` 属性で全体を出す。ブロック幅は自動拡張しない (Q5)。
 *
 * ``testIdPrefix`` / ``maxWidth`` の既定値で Subsystem の従来挙動 (testid 含む) を
 * 完全維持する。``PythonFunction`` は中央 glyph と重ならないよう ``maxWidth="30%"``
 * を渡す (30% + glyph 36% + 30% ≤ 100% の幾何不変式、ADR-0074 §論点 6)。
 */
function PortSideLabels({
  labels,
  flipped,
  testIdPrefix = "subsystem",
  maxWidth = "45%",
}: {
  labels: SubsystemPortLabelInfo;
  flipped: boolean;
  testIdPrefix?: string;
  maxWidth?: string;
}): JSX.Element {
  const inputSide = flipped ? { right: 4 } : { left: 4 };
  const outputSide = flipped ? { left: 4 } : { right: 4 };
  const labelCls =
    "absolute -translate-y-1/2 truncate text-[9px] leading-none text-slate-800";
  return (
    <div className="pointer-events-none absolute inset-0">
      {labels.inputs.map(({ portIdx, label }) => (
        <span
          key={`in-${portIdx}`}
          data-testid={`${testIdPrefix}-port-label-in-${portIdx}`}
          className={labelCls}
          title={label}
          style={{
            top: `${((portIdx + 1) * 100) / (labels.nDataIn + 1)}%`,
            maxWidth,
            ...inputSide,
          }}
        >
          {label}
        </span>
      ))}
      {labels.outputs.map(({ portIdx, label }) => (
        <span
          key={`out-${portIdx}`}
          data-testid={`${testIdPrefix}-port-label-out-${portIdx}`}
          className={labelCls}
          title={label}
          style={{
            top: `${((portIdx + 1) * 100) / (labels.nOut + 1)}%`,
            maxWidth,
            ...outputSide,
          }}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

/** SPEC-0024: PythonFunction の cached spec からラベル情報を組む (無名 = 非表示)。 */
function collectPythonFunctionPortLabels(
  params: Record<string, unknown>,
): SubsystemPortLabelInfo {
  const spec = getCachedPythonSpec(params.code);
  const out: SubsystemPortLabelInfo = { inputs: [], outputs: [], nDataIn: 1, nOut: 1 };
  if (spec === undefined || !spec.resolved) return out;
  out.nDataIn = spec.n_inputs;
  out.nOut = spec.n_outputs;
  spec.input_names.forEach((label, portIdx) => {
    if (label !== "") out.inputs.push({ portIdx, label });
  });
  spec.output_names.forEach((label, portIdx) => {
    if (label !== "") out.outputs.push({ portIdx, label });
  });
  return out;
}

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
  // v0.15.0: リファレンスツールの "Flip Block" 相当の左右反転。SVG ShapeOutline のみ
  // scaleX(-1) で鏡像化 (= 三角形 ▶→◀)。Handle は flipPosition で position prop
  // 反転 (= chevron 向きと data-handlepos が反転して edge anchor が追従)。
  // ShapeContent (テキスト) は反転せず、flipped を渡して justify を切り替えて
  // 「底辺寄り」を維持。z-order は SVG → ShapeContent → Handles で drag 可能。
  const flipped = (data.flipped as boolean | undefined) ?? false;
  // リファレンスツール風: 接続済みのポートでは chevron ``>`` を抑制 (= edge 矢印 head と
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

  // ADR-0058 §論点 4 / §論点 11: Subsystem の trigger / enable slot 識別を
  // ``params.blocks`` filter ベースで一度だけ算出。下記の slot 描画 / 中央
  // indicator / handle position 全てが共有する。
  const controlSlots = resolveControlSlots(
    data.params as Record<string, unknown> | undefined,
  );

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
          業界標準ブロック線図ツール / 数値計算 IDE ライクに、連結線は隠して **コーナー + 辺中央の小さい
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
          controlSlots={controlSlots}
        />
        {Array.from({ length: nIn }, (_, i) => {
          const ph = inputHandlePosition(
            shape,
            i,
            nIn,
            data.blockType,
            controlSlots,
          );
          const finalPos = flipped ? flipPosition(ph.position) : ph.position;
          // ADR-0054 / ADR-0058 §論点 11: trigger / enable slot は接続済でも
          // glyph を維持 (= 制御アイデンティティを視覚で常時提示)。slot 順序は
          // [data..., enable, trigger] (= ADR-0058 §論点 4)。
          const isTriggerSlot = controlSlots.hasTrigger && i === nIn - 1;
          const enableSlotIdx = controlSlots.hasEnable
            ? nIn - 1 - (controlSlots.hasTrigger ? 1 : 0)
            : -1;
          const isEnableSlot = controlSlots.hasEnable && i === enableSlotIdx;
          const isControlSlot = isTriggerSlot || isEnableSlot;
          const showGlyph = isControlSlot || !connectedInputs.has(i);
          return (
            <Handle
              key={`in-${i}`}
              type="target"
              position={finalPos}
              id={String(i)}
              style={arrowHandleStyle(ph.pos)}
            >
              {showGlyph &&
                (isControlSlot ? (
                  <span style={triggerGlyphStyle} />
                ) : (
                  <span style={chevronStyleFor(finalPos, flipped)} />
                ))}
            </Handle>
          );
        })}
        {Array.from({ length: nOut }, (_, i) => {
          const ph = outputHandlePosition(shape, i, nOut);
          const finalPos = flipped ? flipPosition(ph.position) : ph.position;
          const showChevron = !connectedOutputs.has(i);
          return (
            <Handle
              key={`out-${i}`}
              type="source"
              position={finalPos}
              id={String(i)}
              style={arrowHandleStyle(ph.pos)}
            >
              {showChevron && <span style={chevronStyleFor(finalPos, flipped)} />}
            </Handle>
          );
        })}
      </div>
      {/* ID ラベル: absolute で React Flow のノード境界 BOX の **下** に escape させる。
          SPEC-0022: dblclick / F2 (renameRequest) で inline rename に切り替わる。 */}
      <BlockIdLabel blockId={id} />
    </div>
  );
}

/**
 * ノード下の block id ラベル + inline rename (SPEC-0022 §機能要件 1)。
 *
 * dblclick または F2 (store の ``renameRequest`` 経由) で編集モードに入り、
 * Enter 確定 / Escape 取消 / blur 確定。IME composition 中の Enter / Escape は
 * 変換操作として IME に渡す (ADR-0071 §(11))。検証 NG 時は確定を拒否して
 * エラーを表示し、編集モードを維持する (SPEC-0022 §機能要件 3)。
 */
export function BlockIdLabel({ blockId }: { blockId: string }): JSX.Element {
  const { t } = useTranslation();
  const renameRequest = useAppStore((s) => s.renameRequest);
  const editor = useBlockRenameEditor(blockId);
  const { start } = editor;

  // F2 / メニューからの rename 要求 (nonce 単調増加で同一ブロック連打にも反応)
  useEffect(() => {
    if (renameRequest && renameRequest.blockId === blockId) {
      start();
    }
  }, [renameRequest, blockId, start]);

  if (!editor.editing) {
    return (
      <div
        className="absolute left-1/2 top-full mt-1 -translate-x-1/2 cursor-text whitespace-nowrap text-center text-[10px] font-medium leading-tight text-slate-700"
        data-testid="block-id-label"
        onDoubleClick={(e) => {
          // Subsystem の dblclick ドリルダウン (DiagramCanvas.onNodeDoubleClick)
          // と衝突させない
          e.stopPropagation();
          start();
        }}
      >
        {blockId}
      </div>
    );
  }
  return (
    <div
      className="nodrag nopan absolute left-1/2 top-full mt-1 -translate-x-1/2 text-center"
      onDoubleClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <input
        ref={editor.inputRef}
        className={`${INPUT_CLS} w-32 text-center text-[10px]`}
        data-testid="block-id-input"
        aria-label={t("diagram.rename.aria_label")}
        value={editor.draft}
        onChange={(e) => editor.setDraft(e.target.value)}
        onCompositionStart={editor.handleCompositionStart}
        onCompositionEnd={editor.handleCompositionEnd}
        onKeyDown={editor.handleKeyDown}
        onBlur={editor.handleBlur}
      />
      {editor.error !== null && (
        <div
          className="mt-0.5 whitespace-nowrap text-[9px] text-rose-600"
          data-testid="block-id-error"
        >
          {t(`diagram.rename.${editor.error.code}`, {
            conflictId: editor.error.conflictId ?? "",
          })}
        </div>
      )}
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
  // リファレンスツール風: 細黒線 + 白背景 + フラット (drop-shadow なし)。selected は薄青、
  // container だけ僅かに色を変える程度で、通常時は完全モノトーン。
  const stroke = selected ? "#2563eb" : "#1e293b";
  // リファレンスツール風: 通常も Subsystem も白背景、container 識別は二重枠で行う
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
        // リファレンスツール風: 角丸なし、塗り潰しは細い黒バー
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
        // 右辺が尖る五角形タグ (From: 矢印頭。v0.53.5 実物画像準拠)
        <polygon
          points={`1,1 ${w - h / 2 - 1},1 ${w - 1},${h / 2} ${w - h / 2 - 1},${h - 1} 1,${h - 1}`}
          {...commonProps}
        />
      )}
      {kind === "trapezoid-l" && (
        // 左辺が左向きに尖る五角形タグ (Goto = From の左右鏡像)。
        // v0.53.7: ユーザー指摘「gotoだけ切り込みの方向が左右逆」で確定。
        // v0.53.5-6 の左辺凹み (tag-notch-l) は向きが実物と逆だった。
        // 尖り頂点 = bbox 左辺中央 → 入力配線の矢印頭がちょうど頂点に刺さる。
        <polygon
          points={`${h / 2 + 1},1 ${w - 1},1 ${w - 1},${h - 1} ${h / 2 + 1},${h - 1} 1,${h / 2}`}
          {...commonProps}
        />
      )}
      {kind === "stadium" && (
        // 角丸カプセル (Inport / Outport): rx = 高さの半分で両端が半円
        <rect
          x={1}
          y={1}
          width={w - 2}
          height={h - 2}
          rx={(h - 2) / 2}
          ry={(h - 2) / 2}
          {...commonProps}
        />
      )}
      {(kind === "rect" || kind === "rect-wide") && (
        // リファレンスツール風: 角丸なし。Subsystem も他のブロックと同じ単枠
        // (= ユーザー要望、二重枠は廃止)。
        <rect x={1} y={1} width={w - 2} height={h - 2} {...commonProps} />
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Inner content (glyph or text) per kind
// ---------------------------------------------------------------------------

/** ADR-0079 Stage 3: ``Reduce.operation`` → ブロック面の記号 (Python 側 REDUCE_OPERATIONS と一致)。 */
const REDUCE_OPERATION_SYMBOLS: Readonly<Record<string, string>> = {
  sum: "Σ",
  product: "Π",
  min: "min",
  max: "max",
  mean: "mean",
};

function ShapeContent({
  shape,
  typePath,
  blockId,
  color,
  param,
  paramsRaw,
  flipped = false,
  controlSlots = { hasTrigger: false, hasEnable: false },
}: {
  shape: BlockShape;
  typePath: string;
  blockId: string;
  color: string;
  param: string | null;
  paramsRaw: Record<string, unknown>;
  flipped?: boolean;
  // ADR-0058 §論点 11 (code-reviewer SHOULD 1): 親コンポーネントで一度算出した
  // control slot 情報を再利用 (DRY、二重 ``inner.some(...)`` 走査を回避)。
  controlSlots?: { hasTrigger: boolean; hasEnable: boolean };
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

  // カプセル (Inport / Outport): リファレンスツール風にポート番号 (= port_idx + 1) を表示。
  // kind ではなく typePath で判定する (= shape 変更に追従して番号表示が消えない)。
  if (typePath === INPORT_TYPE || typePath === OUTPORT_TYPE) {
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

  // rect-wide (TransferFunction 等): リファレンスツール風に **実際の式** を 2 行表示する。
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

  // ADR-0058 §論点 1 / §論点 11: Subsystem に内部 Trigger / Enable があれば、
  // 上辺左に小さな indicator アイコンを 12×12 SVG で重ねる (= 制御アイデンティティ
  // を視覚で示す、ADR-0054 を一般化)。識別の真実源は class 名から内部 control
  // block の有無 (= filter ベース) に移行。両方ある時は横並びで両方描画。
  // controlSlots は親コンポーネントで一度算出した結果を受け取る (DRY)。
  if (typePath.endsWith(".Subsystem")) {
    // SPEC-0022 §機能要件 7: 内部 Inport / Outport が rename されていれば、その
    // id を外面のポート脇 (入力=内側左寄せ / 出力=内側右寄せ) に表示する。
    // 既定 id (Inport_0 等) も含めて常時表示 (2026-08-25 Q6 撤回)。中央は従来どおり空
    // (ADR-0021、リファレンスツール互換)。
    const portLabels = collectSubsystemPortLabels(paramsRaw);
    const hasIndicator = controlSlots.hasTrigger || controlSlots.hasEnable;
    const hasLabels =
      portLabels.inputs.length > 0 || portLabels.outputs.length > 0;
    if (!hasIndicator && !hasLabels) {
      return <></>;
    }
    return (
      <>
        {hasIndicator && (
          <div
            data-testid="subsystem-control-indicator"
            className="absolute inset-y-0 left-0 flex items-start gap-0.5 pl-1 pt-1"
            style={{ color }}
          >
            {controlSlots.hasEnable && (
              <EnableIndicatorGlyph className="h-3 w-3" />
            )}
            {controlSlots.hasTrigger && (
              <TriggerIndicatorGlyph className="h-3 w-3" />
            )}
          </div>
        )}
        {hasLabels && (
          <PortSideLabels labels={portLabels} flipped={flipped} />
        )}
      </>
    );
  }
  // rect (default): リファレンスツール風の専用 render を type ごとに優先する
  //   - Constant: 値そのものを大きく表示 (= "1.0", "70" 等)
  //   - Integrator: ``1/s``
  //   - UnitDelay: ``1/z``
  //   - ZeroOrderHoldDirect: 階段保持アイコン (= 既存 glyph)
  //   - Derivative: ``s`` (= du/dt)
  //   - param がある (Step, Sine, ...) → 左 glyph 小 + 右 param
  //   - param がない (Abs, Sign, ...) → glyph 大、中央
  if (typePath.endsWith(".Constant")) {
    const params = paramsRaw as Record<string, unknown>;
    const dtypeParam = typeof params.dtype === "string" ? params.dtype : "auto";
    if (dtypeParam !== "auto") {
      // SPEC-0028 Q9 (SM-D Stage 1): 実 dtype 宣言時は**生値 + dtype 名**を表示。
      // 変換値の計算は frontend で再実装しない (ADR-0077 §データ整合性 1)。
      // formatNumber は文字列 (mask placeholder "$Kp" 等) を素通しする
      return (
        <div className="absolute inset-0 flex flex-col items-center justify-center font-mono text-slate-800">
          <span className="truncate px-1 text-[12px] font-semibold tabular-nums">
            {formatValue(params.value)}
          </span>
          <span
            data-testid="constant-dtype-label"
            className="text-[8px] leading-tight text-slate-500"
          >
            {dtypeParam}
          </span>
        </div>
      );
    }
    // v0.56.0 (output_type 撤去): 未宣言 (auto) は生値のみ表示
    // (ADR-0079 Stage 3: 配列 value は ``[1, 2, 3]`` / ``[2×2]`` と短く整形)
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[12px] font-semibold tabular-nums text-slate-800">
        <span className="truncate px-1">{formatValue(params.value)}</span>
      </div>
    );
  }
  // Cast の面表示は**変換後の型名** (ユーザー要望 2026-09-04 で固定テキスト `cast`
  // から変更)。v0.56.0 (output_type 撤去): dtype 名を常時表示 (既定 float64)。
  // パレット glyph は `cast` のまま (ブロックの正体)。
  if (typePath.endsWith(".Cast")) {
    const castParams = paramsRaw as Record<string, unknown>;
    const label =
      typeof castParams.dtype === "string" ? castParams.dtype : "float64";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span className="truncate px-1">{label}</span>
      </div>
    );
  }
  if (typePath.endsWith(".Integrator")) {
    return <TransferFunctionFraction num="1" den="s" />;
  }
  if (typePath.endsWith(".UnitDelay")) {
    return <TransferFunctionFraction num="1" den="z" />;
  }
  // v0.36.4: フォントを MinMax / Integrator (TransferFunctionFraction) と統一
  // (非 italic、ユーザー指摘 2026-05-17)。``s`` は数学変数なので慣習上 italic でも
  // 自然だが、Canvas 上の他ブロックと見た目を揃える整合性を優先する。
  if (typePath.endsWith(".Derivative")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[14px] font-medium text-slate-800">
        <span>s</span>
      </div>
    );
  }
  // Abs: リファレンスツール風に ``|u|`` テキスト。v0.36.4: フォント統一 (非 italic)。
  if (typePath.endsWith(".Abs")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[13px] font-medium text-slate-800">
        <span>|u|</span>
      </div>
    );
  }
  // ADR-0079 Stage 3: Reduce は operation に応じた記号 (Σ / Π / min / max / mean)
  if (typePath.endsWith(".Reduce")) {
    const op = (paramsRaw as Record<string, unknown>).operation;
    const label =
      (typeof op === "string" ? REDUCE_OPERATION_SYMBOLS[op] : undefined) ??
      REDUCE_OPERATION_SYMBOLS.sum;
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[13px] font-medium text-slate-800">
        <span>{label}</span>
      </div>
    );
  }
  // MinMax: param.operator ("min" / "max") をそのままテキスト表示
  // (= flode 側の MinMax の param 名は ``operator`` であって ``function`` ではない)
  if (typePath.endsWith(".MinMax")) {
    const op = (paramsRaw as Record<string, unknown>).operator;
    const label = op === "max" ? "max" : "min";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>{label}</span>
      </div>
    );
  }
  // SPEC-0003 / ADR-0055: tag ベース仮想配線。中央に tag ラベルを表示し、
  // ラベルは両方 ``[tag]`` (v0.53.5: 実物画像準拠で From の ``>tag>`` を廃止)。
  // 種別は外形 (Goto = 左向き尖り (From の鏡像) / From = 右向き尖り) で識別する。
  // Goto/From 間に wire は描かない (= tag だけで対応を示す、SPEC §7)。
  // GotoTagVisibility (Scoped 用) は Amendment (2026-05-19) で Phase 2 送り。
  if (typePath.endsWith(".Goto") || typePath.endsWith(".From")) {
    const getTag = (p: Record<string, unknown>): string =>
      typeof p.tag === "string" ? p.tag : "?";
    const tag = getTag(paramsRaw);
    const isGoto = typePath.endsWith(".Goto");
    const label = `[${tag}]`;
    const testId = isGoto ? "goto-label" : "from-label";
    // 五角形タグの尖り (Goto 左辺 / From 右辺) 分だけラベルを内側に寄せる。
    // v0.53.7: Goto は From の左右鏡像 (左辺尖り h/2) なので padding も鏡像
    const padCls = isGoto ? "pl-3 pr-1" : "pl-1 pr-3";
    return (
      <div
        data-testid={testId}
        className={`absolute inset-0 flex items-center justify-center ${padCls} font-mono text-[11px] font-semibold text-slate-800`}
      >
        <span className="truncate">{label}</span>
      </div>
    );
  }

  // v0.35.7: Switch をリファレンスツール流の per-port 表示に。
  // v0.35.8: 「スイッチっぽさ」を出すため、右半分に物理的スイッチアームの SVG
  // を描き込む。スイッチアームは "T 側に倒れている" 既定姿で描画
  // (= 内部状態がない static icon、リファレンスツールの Switch ブロック表示と同様)。
  //   - 上ポート (u[0] = input_true)  → "T"
  //   - 中央ポート (u[1] = control)   → "{op} {threshold}" (例 "≥ 0")
  //   - 下ポート (u[2] = input_false) → "F"
  if (typePath.endsWith(".Switch")) {
    const params = paramsRaw as Record<string, unknown>;
    const criterion = params.criterion;
    const threshold = params.threshold;
    const opSymbol =
      criterion === ">"
        ? ">"
        : criterion === "!="
          ? "≠"
          : "≥"; // ">=" default
    const thrText =
      typeof threshold === "number" ? formatNumber(threshold) : "0";
    const middleLabel = `${opSymbol} ${thrText}`;
    const portLabels = ["T", middleLabel, "F"];
    return (
      <div className="pointer-events-none absolute inset-0">
        {/* per-port ラベル (左寄せ) */}
        {portLabels.map((label, i) => (
          <span
            key={i}
            className={`absolute left-1 -translate-y-1/2 font-mono leading-none text-slate-800 ${
              i === 1 ? "text-[9px]" : "text-[10px] font-bold"
            }`}
            style={{ top: `${((i + 1) * 100) / (3 + 1)}%` }}
          >
            {label}
          </span>
        ))}
        {/* v0.35.10: ブロック実寸を viewBox に使って circle / line を絶対 px で
            描画する。これで縦長/横長どちらにリサイズしても接点は完全な円、線は
            均一太さを保ち、かつポート y 位置 (= (i+1)/(n+1)) とぴったり揃う
            (ユーザー指摘「横に拡大したときも考えてる?」)。 */}
        <svg
          width={shape.width}
          height={shape.height}
          viewBox={`0 0 ${shape.width} ${shape.height}`}
          className="absolute inset-0"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {/* T 接点 (= 上ポート y 位置、ブロック右寄り 60% 位置) */}
          <circle
            cx={shape.width * 0.6}
            cy={shape.height * 0.25}
            r="3.5"
            fill="currentColor"
            stroke="none"
          />
          {/* F 接点 (= 下ポート y 位置、同じ x) */}
          <circle
            cx={shape.width * 0.6}
            cy={shape.height * 0.75}
            r="3.5"
            fill="currentColor"
            stroke="none"
          />
          {/* 出力 pivot (= 右端寄り、ブロック中央 y) */}
          <circle
            cx={shape.width - 8}
            cy={shape.height * 0.5}
            r="3.5"
            fill="currentColor"
            stroke="none"
          />
          {/* スイッチアーム = T 側に倒れている (pivot → T 接点を斜め直線で結ぶ) */}
          <line
            x1={shape.width - 8}
            y1={shape.height * 0.5}
            x2={shape.width * 0.6}
            y2={shape.height * 0.25}
          />
        </svg>
      </div>
    );
  }
  // Sign: リファレンスツール風に ``sign`` テキスト。
  // v0.36.4: フォントを MinMax (非 italic) と統一 (ユーザー指摘 2026-05-17)。
  if (typePath.endsWith(".Sign")) {
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>sign</span>
      </div>
    );
  }
  // v0.36.2: MathFunction / TrigFunction をリファレンスツール風に **選択された関数名** で
  // 表示する (= MinMax の "min"/"max" と同じパターン)。glyph (f(u) / 正弦波) では
  // どの関数が選ばれているか分からないという指摘 (ユーザー 2026-05-17) への対応。
  // v0.36.3: フォントスタイルを MinMax (非 italic) と揃える (ユーザー指摘 2026-05-17)。
  if (
    typePath.endsWith(".MathFunction") ||
    typePath.endsWith(".TrigFunction")
  ) {
    const fn = (paramsRaw as Record<string, unknown>).function;
    const label = typeof fn === "string" ? fn : "?";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>{label}</span>
      </div>
    );
  }
  // v0.36.2: CompareToConstant をリファレンスツール風に ``u op c`` 表示。
  // 演算子は Unicode (≥ / ≤ / ≠ / =) で短縮、定数は formatNumber で省略表記。
  if (typePath.endsWith(".CompareToConstant")) {
    const params = paramsRaw as Record<string, unknown>;
    const opSym = compareOpSymbol(params.op);
    const constText =
      typeof params.const === "number" ? formatNumber(params.const) : "?";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>{`u ${opSym} ${constText}`}</span>
      </div>
    );
  }
  // v0.36.2: CompareToZero をリファレンスツール風に ``u op 0`` 表示 (= const=0 固定の特殊化)。
  if (typePath.endsWith(".CompareToZero")) {
    const opSym = compareOpSymbol(
      (paramsRaw as Record<string, unknown>).op,
    );
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-medium text-slate-800">
        <span>{`u ${opSym} 0`}</span>
      </div>
    );
  }
  // v0.35.4: Divide: per-port に '×' / '÷' を表示 (signs = "*/" 等)。
  // Add / Sum (v0.35.2 / .3) と統一。
  if (typePath.endsWith(".Divide")) {
    const signs =
      typeof (paramsRaw as Record<string, unknown>).signs === "string"
        ? ((paramsRaw as Record<string, unknown>).signs as string)
        : "*/";
    const n = signs.length;
    return (
      <div className="pointer-events-none absolute inset-0">
        {Array.from(signs).map((s, i) => (
          <span
            key={i}
            className="absolute left-1 -translate-y-1/2 font-mono text-[12px] font-bold leading-none text-slate-800"
            style={{ top: `${((i + 1) * 100) / (n + 1)}%` }}
          >
            {s === "/" ? "÷" : "×"}
          </span>
        ))}
      </div>
    );
  }

  // v0.35.2: Add: リファレンスツール流に **各入力ポート位置に signs を表示**。
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

  // Logical / Relational: param.operator を中央表示。
  // Logical は IEC 61131-3 FBD 流の機能名テキスト (AND / OR / ...) をそのまま。
  // Relational は ADR-0070: ASCII 二重字 (<= 等) を CompareTo 系と同じ
  // compareOpSymbol で JIS Z 8201 の数学記号 (≤ / ≥ / ≠ / =) にして表示する
  // (param 値・enum は ASCII のまま、表示のみ変換)。
  if (
    typePath.endsWith(".LogicalOperator") ||
    typePath.endsWith(".RelationalOperator")
  ) {
    const op = (paramsRaw as Record<string, unknown>).operator;
    const display =
      typeof op === "string"
        ? typePath.endsWith(".RelationalOperator")
          ? compareOpSymbol(op)
          : op
        : "?";
    return (
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] font-semibold text-slate-800">
        <span>{display}</span>
      </div>
    );
  }

  // v0.47.0: Trigger は trigger_type に応じてエッジ記号を描き分ける (rising ↑ /
  // falling ↓ / either ↕ / function-call f())。palette glyph は rising 固定。
  if (typePath === TRIGGER_TYPE) {
    const raw = (paramsRaw as Record<string, unknown>).trigger_type;
    const mode: TriggerEdgeMode =
      raw === "falling" || raw === "either" || raw === "function-call"
        ? raw
        : "rising";
    return (
      <div
        className="absolute inset-0 flex items-center justify-center px-1.5"
        style={{ color }}
        data-testid={`trigger-glyph-${mode}`}
      >
        <div className="h-[70%] w-[80%]">
          <TriggerEdgeGlyph mode={mode} />
        </div>
      </div>
    );
  }

  // SPEC-0024: PythonFunction はポート名 (introspect 結果、無名は非表示) を
  // Subsystem と同じ流儀で描く。ラベルがあるときだけ中央の `def` glyph を
  // 36% に縮め、ラベル 30% + glyph 36% + ラベル 30% ≤ 100% で重なりを防ぐ
  // (ADR-0074 §論点 6 の幾何不変式)。名前を付けない限り見た目は従来どおり。
  if (typePath === PYTHON_FUNCTION_TYPE) {
    const pfLabels = collectPythonFunctionPortLabels(paramsRaw);
    const hasPfLabels = pfLabels.inputs.length > 0 || pfLabels.outputs.length > 0;
    return (
      <>
        <div
          className="absolute inset-0 flex items-center justify-center px-1.5"
          style={{ color }}
        >
          <div className={hasPfLabels ? "h-[70%] w-[36%]" : "h-[70%] w-[80%]"}>
            <BlockGlyph typePath={typePath} />
          </div>
        </div>
        {hasPfLabels && (
          <PortSideLabels
            labels={pfLabels}
            flipped={flipped}
            testIdPrefix="pythonfunction"
            maxWidth="30%"
          />
        )}
      </>
    );
  }

  // それ以外の rect: リファレンスツール風に **glyph を中央大きく** 配置 (param 値の併記は
  // しない、リファレンスツールも icon only)。param 値はパラメータパネルで見る。
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
      return 4; // Mux/Demux はリファレンスツール風の細い black bar、最低限の視認性のみ確保
    case "circle":
      return 28;
    case "triangle-r":
      return 32;
    case "trapezoid-l":
    case "trapezoid-r":
    case "stadium":
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
    case "stadium":
    case "trapezoid-l":
    case "trapezoid-r":
      // v0.47.0: 境界 / タグ系は既定 26〜28 なので最小値も下げる。幅側
      // (minWidthForKind) は既存の 36 / 40 で既定幅 44 / 72 を下回るため変更なし
      return 20;
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

// ADR-0054: Handle の配置軸は (a) 縦軸上に topPct% で打つ (左辺 / 右辺 Handle)
// / (b) 横軸上に leftPct% で打つ (上辺 Handle) の 2 通り。両方同時に指定される
// ことはないので discriminated union で型レベルに exclusivity を強制する。
type HandlePos =
  | { axis: "y"; topPct: number }
  | { axis: "x"; leftPct: number };

function arrowHandleStyle(pos: HandlePos): React.CSSProperties {
  // v0.20.4: Handle を 24×24 に拡大して chevron ``>`` (= Handle 中心から外側
  // +6〜+12 px の位置) を hit area に含める。
  //
  // v0.20.9: v0.20.8 で transform を override して Handle center を node 境界
  // にロックしようとしたが、Handle が node 内側 24 px に押し込まれて chevron
  // がブロック内に表示される問題発生 (ユーザー指摘「ポート位置を変更するな」)
  // → React Flow デフォルト transform に戻して chevron は node 外側のままに。
  // edge と node の隙間は React Flow デフォルト挙動 (Handle center が node
  // 境界の少し外側) と markerEnd 削除 (v0.20.7) で当面我慢する。
  const base: React.CSSProperties = {
    background: "transparent",
    width: 24,
    height: 24,
    border: "none",
    borderRadius: 0,
  };
  if (pos.axis === "x") {
    return { ...base, left: `${pos.leftPct}%` };
  }
  return { ...base, top: `${pos.topPct}%` };
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

// ADR-0054 → ADR-0058: Subsystem 内部 Trigger / Enable control block の上辺
// slot を識別するための
// 縦向き chevron (= ``v``)。色は amber-500 でデータ chevron (slate-600) と
// 差別化する。rotate(135deg) で borderTop+borderRight の corner を下向きに
// 倒した結果が ``v`` (= 信号が上から下に流れる慣習)。
// transform 計算: translate の単位 % は **自要素 (= width/height) サイズ基準**。
// width=height=6px なので ``-50%`` = -3px 中央寄せ、``-150%`` は更に追加で
// -6px (= chevron 1 個分) を上方向に押し出した結果、Handle 中心 (= ブロック
// 境界線) から外側へ chevron 1 個分シフトする。``chevronStyleFor`` の左辺版
// ``translate(-150%, -50%)`` と数値的に対称。
const triggerGlyphStyle: React.CSSProperties = {
  position: "absolute",
  top: "50%",
  left: "50%",
  width: 6,
  height: 6,
  borderTop: "1.75px solid #f59e0b",
  borderRight: "1.75px solid #f59e0b",
  transform: "translate(-50%, -150%) rotate(135deg)",
  pointerEvents: "none",
};

/**
 * 全 shape 共通: chevron ``>`` を Handle 中心 (= ブロック境界線上) からさらに
 * 1 chevron 分 (= 6px) **外側** に押し出す。input (Position.Left) は左へ、output
 * (Position.Right) は右へ。これによりブロック種別 (rect / bar / circle / triangle
 * 等) に関わらず chevron 位置が統一され、リファレンスツールの見た目に揃う。
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
// リファレンスツール風: 分数形式で num / den を 2 行表示する小さな helper component。
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
  _typePath: string, // ADR-0058: filter ベース化で未使用、API 互換のため残置
  controlSlots: { hasTrigger: boolean; hasEnable: boolean } = {
    hasTrigger: false,
    hasEnable: false,
  },
): { position: Position; pos: HandlePos } {
  // ADR-0058 §論点 4 / §論点 11 / ADR-0054 継承: slot 順序
  // [data_inports..., enable_slot, trigger_slot]。
  // - trigger slot (= 末尾): 上辺中央 (Position.Top + leftPct=50)
  // - enable slot (trigger 並存時: 末尾-1、enable のみ: 末尾): 上辺左寄せ
  //   (leftPct=25、trigger と並ぶときの中心は 50 + 25 で物理的に離す)
  // - データ入力 (左辺): 残りの縦軸に等間隔配置
  const triggerSlotIdx = controlSlots.hasTrigger ? n - 1 : -1;
  const enableSlotIdx = controlSlots.hasEnable
    ? n - 1 - (controlSlots.hasTrigger ? 1 : 0)
    : -1;
  if (i === triggerSlotIdx) {
    return { position: Position.Top, pos: { axis: "x", leftPct: 50 } };
  }
  if (i === enableSlotIdx) {
    // trigger 並存時は左寄せ (= trigger の中央 50 と物理的に分離して識別)、
    // enable のみの時は中央 50 (= 単独 trigger と同じ位置)。
    return {
      position: Position.Top,
      pos: { axis: "x", leftPct: controlSlots.hasTrigger ? 25 : 50 },
    };
  }
  // 単一入力 + 単数前提形状 (三角形 / 円 / バー)。複数あれば縦に並べる。
  // 三角形 / 円 / バー は全部「左辺に等間隔配置」で OK (制御 slot を持たない)。
  if (
    shape.kind === "triangle-r" ||
    shape.kind === "circle" ||
    shape.kind === "bar"
  ) {
    return {
      position: Position.Left,
      pos: { axis: "y", topPct: ((i + 1) * 100) / (n + 1) },
    };
  }
  // control slot を除いたデータ入力本数で等分配する (= 末尾 control slot 分の
  // 縦間隔が空かないように)。control なしのときは従来通り n で等分配。
  const nControl =
    (controlSlots.hasTrigger ? 1 : 0) + (controlSlots.hasEnable ? 1 : 0);
  const dataN = n - nControl;
  const denom = dataN < 1 ? n + 1 : dataN + 1;
  return {
    position: Position.Left,
    pos: { axis: "y", topPct: ((i + 1) * 100) / denom },
  };
}

function outputHandlePosition(
  shape: BlockShape,
  i: number,
  n: number,
): { position: Position; pos: HandlePos } {
  // 三角形 (Gain): 出力は頂点 1 点 → 中央。複数想定なし。
  // 円 (Sum/Product/Divide): n_outputs=1 確定なので中央でよい。複数になることはない。
  // バー / カプセル / 五角形タグ / その他: 右辺に等間隔配置。
  if (shape.kind === "triangle-r" || shape.kind === "circle") {
    return {
      position: Position.Right,
      pos: { axis: "y", topPct: 50 },
    };
  }
  return {
    position: Position.Right,
    pos: { axis: "y", topPct: ((i + 1) * 100) / (n + 1) },
  };
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
// 最新サンプルをブロックフェース上に大きく描画する (リファレンスツールの Display 相当)。
// ---------------------------------------------------------------------------

/** @internal テスト用 export。プロダクション利用は BlockNodeView 経由。 */
export function DisplayLiveValue({ blockId }: { blockId: string }): JSX.Element {
  // ADR-0023: scopes[blockId] は SoA ScopeBuffer (Float64Array 列指向)。
  // 最新サンプル (= 各信号の length-1 番目の要素) を集める。
  const buffer = useAppStore((s) => s.scopes[blockId]);
  // SPEC-0028 Q8 (SM-D Stage 1): 記録値は float64 のまま、**表示整形だけ**
  // 解決済み dtype に従う (整数 → 小数点なし、bool → true/false)。
  // dtype は backend の resolve-dtypes 結果 (store) から取る — 再計算しない
  useDtypeResolution();
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
          {formatDisplayValue(v, dtypeForPort(blockId, "in", i))}
        </span>
      ))}
    </div>
  );
}

/** @internal テスト用 export。dtype は解決済みの表示整形ヒント (SPEC-0028 Q8)。 */
export function formatDisplayValue(v: number, dtype?: string | null): string {
  if (dtype === "bool") return v !== 0 ? "true" : "false";
  if (dtype === "int32" || dtype === "int64" || dtype === "uint8") {
    if (Number.isFinite(v)) return Math.round(v).toString();
  }
  if (!Number.isFinite(v)) return String(v);
  if (Math.abs(v) >= 10000 || (Math.abs(v) < 0.001 && v !== 0)) {
    return v.toExponential(2);
  }
  return v.toFixed(3);
}

// Re-export type for external consumers (referenced in App / DiagramCanvas if needed)
export type { BlockShapeKind };
