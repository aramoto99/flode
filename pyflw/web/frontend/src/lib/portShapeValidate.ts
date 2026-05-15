// ADR-0019 §(6): port shape の整合性をフロントで pre-validate するヘルパ。
// strict 一致 (broadcasting なし、ADR-0017 §(4))。

import type { BlockEntry, BlockMetadata } from "../types/api";
import { INPORT_TYPE, OUTPORT_TYPE, TRIGGERED_SUBSYSTEM_TYPE } from "./blockTypes";
import { hasDynamicPorts, resolvePortCounts } from "./dynamicPorts";

export function shapeEquals(a: number[], b: number[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export function formatShape(shape: number[]): string {
  if (shape.length === 0) return "scalar ()";
  // numpy-like: rank-1 は trailing comma 付き、rank>=2 は通常の tuple 表記
  if (shape.length === 1) return `(${shape[0]},)`;
  return `(${shape.join(",")})`;
}

/**
 * 1 block の port_shapes_in/out を、registry の default を base に
 * その block の現在の n_inputs / n_outputs に合わせて推定する。
 *
 * ADR-0019 §6.1: param 変更で port 数が変わるブロック (Scope / Sum / Product /
 * Mux / Demux / StateSpace 等、``hasDynamicPorts`` で判定) は ``resolvePortCounts``
 * で実 count を取得し、registry default の port shape を **末端複製 / 切詰め** で
 * 実 count に合わせる。例: Scope の n_inputs=2 → in = [[], []]、Sum の signs="+++"
 * → in = [[], [], []]。Mux の出力 ``[n]`` のような **param 依存 shape** までは
 * 反映しない (= count の修正のみ、shape は registry default を踏襲)。
 *
 * ADR-0039: Subsystem / TriggeredSubsystem は ``params.blocks`` 内の Inport /
 * Outport から派生する。registry default (= 空 Subsystem の port_shapes、
 * `n_inputs=0` / `n_outputs=0`) では新規 Inport を追加しても connect 検証で
 * 弾かれるため、本ヘルパで派生計算する。
 */
export function getDefaultPortShapes(
  block: BlockEntry,
  registry: ReadonlyMap<string, BlockMetadata>,
): { in: number[][]; out: number[][] } {
  // ADR-0039: Subsystem / TriggeredSubsystem は内部 Inport/Outport から派生
  if (
    block.type.endsWith(".Subsystem") ||
    block.type.endsWith(".TriggeredSubsystem")
  ) {
    return derivePortShapesFromInner(block);
  }

  const meta = registry.get(block.type);
  if (!meta) {
    return { in: [], out: [] };
  }
  const defaultIn = meta.port_shapes_in_default;
  const defaultOut = meta.port_shapes_out_default;

  // param 変更で port 数が変わるブロック (Scope/Sum/Product/Mux/StateSpace 等)
  // は実 count に合わせて shape 列を resize する。それ以外は registry default
  // をそのまま返す (= 既存挙動を維持)。
  // 注: Subsystem / TriggeredSubsystem も hasDynamicPorts==true だが、上で早期
  // return 済みなので本分岐には到達しない。
  if (!hasDynamicPorts(block.type)) {
    return { in: defaultIn, out: defaultOut };
  }
  const counts = resolvePortCounts(
    block.type,
    block.params as Record<string, unknown>,
    meta,
  );
  return {
    in: resizeShapes(defaultIn, counts.nInputs),
    out: resizeShapes(defaultOut, counts.nOutputs),
  };
}

/**
 * port_shape の列を target count に合わせて resize する。
 *
 * - ``count == defaults.length``: そのまま返す
 * - ``count < defaults.length``: 先頭から ``count`` 個を切り出す
 * - ``count > defaults.length``: 末尾の shape を ``count - defaults.length`` 回複製
 *   (= 動的 port ブロックの可変 input/output は同 shape の追加なので、末尾複製で
 *    実態と一致する。e.g. Scope: ``[[]]`` → ``[[], []]``、Sum: ``[[], []]`` → ``[[], [], []]``)
 * - ``defaults`` が空かつ ``count > 0``: scalar ``[]`` を ``count`` 個並べる
 *   (= registry が n_inputs=0 default のブロック向け fallback)
 */
function resizeShapes(defaults: number[][], count: number): number[][] {
  if (count === defaults.length) return defaults;
  if (count < defaults.length) return defaults.slice(0, count);
  // count > defaults.length
  if (defaults.length === 0) {
    return Array.from({ length: count }, () => [] as number[]);
  }
  const tail = defaults[defaults.length - 1];
  // shape は ``number[]`` の値型なのでシャローコピーで十分。同一参照の使い回しは
  // 呼び出し元で in-place 変更されると他要素まで波及するため避ける。
  const extra = Array.from(
    { length: count - defaults.length },
    () => [...tail],
  );
  return [...defaults, ...extra];
}

/**
 * Subsystem / TriggeredSubsystem の port_shapes を ``params.blocks`` 内の
 * Inport / Outport の port_shape (port_idx 順) から派生計算する。
 *
 * TriggeredSubsystem は trigger 入力分 ``[]`` (= scalar) を ``in`` の末尾に
 * 追加する (ADR-0036 §(2))。
 */
function derivePortShapesFromInner(
  block: BlockEntry,
): { in: number[][]; out: number[][] } {
  const params = block.params as Record<string, unknown>;
  const inner = params.blocks;
  if (!Array.isArray(inner)) {
    // params.blocks 不在 (= drag prefetch 直後 等) は空で返す。Subsystem は
    // 内部に Inport を追加した時点で blocks=[] が必ず存在する。
    const isTriggered = block.type === TRIGGERED_SUBSYSTEM_TYPE;
    return { in: isTriggered ? [[]] : [], out: [] };
  }
  const inports = inner
    .filter(
      (b): b is BlockEntry =>
        typeof b === "object" && b !== null && (b as BlockEntry).type === INPORT_TYPE,
    )
    .map((b) => ({
      port_idx: readPortIdx(b),
      port_shape: readPortShape(b),
    }))
    .sort((a, b) => a.port_idx - b.port_idx)
    .map((p) => p.port_shape);
  const outports = inner
    .filter(
      (b): b is BlockEntry =>
        typeof b === "object" && b !== null && (b as BlockEntry).type === OUTPORT_TYPE,
    )
    .map((b) => ({
      port_idx: readPortIdx(b),
      port_shape: readPortShape(b),
    }))
    .sort((a, b) => a.port_idx - b.port_idx)
    .map((p) => p.port_shape);

  // TriggeredSubsystem の trigger 入力 (= scalar) を末尾に付加
  const inShapes =
    block.type === TRIGGERED_SUBSYSTEM_TYPE ? [...inports, []] : inports;

  return { in: inShapes, out: outports };
}

function readPortIdx(b: BlockEntry): number {
  const v = (b.params as Record<string, unknown>).port_idx;
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function readPortShape(b: BlockEntry): number[] {
  const v = (b.params as Record<string, unknown>).port_shape;
  if (Array.isArray(v) && v.every((x) => typeof x === "number")) {
    return v as number[];
  }
  return []; // default = scalar
}

export interface PortConnectionCheck {
  ok: boolean;
  reason?: string;
}

/**
 * src.out[srcIdx] と dst.in[dstIdx] の shape が一致するかをチェックする。
 *
 * Phase 3 では registry default の port_shapes を使う。動的 (Mux/Demux/Sum) の
 * 場合は呼び出し側で別途 resolve-port-shapes を実行して shape を更新する。
 */
export function validatePortShapeConnection(
  src: BlockEntry,
  srcIdx: number,
  dst: BlockEntry,
  dstIdx: number,
  registry: ReadonlyMap<string, BlockMetadata>,
  overrideShapes?: {
    src?: { in: number[][]; out: number[][] };
    dst?: { in: number[][]; out: number[][] };
  },
): PortConnectionCheck {
  const srcShapes = overrideShapes?.src ?? getDefaultPortShapes(src, registry);
  const dstShapes = overrideShapes?.dst ?? getDefaultPortShapes(dst, registry);

  if (srcIdx < 0 || srcIdx >= srcShapes.out.length) {
    return {
      ok: false,
      reason: `${src.id}.out[${srcIdx}] does not exist (n_outputs=${srcShapes.out.length}).`,
    };
  }
  if (dstIdx < 0 || dstIdx >= dstShapes.in.length) {
    return {
      ok: false,
      reason: `${dst.id}.in[${dstIdx}] does not exist (n_inputs=${dstShapes.in.length}).`,
    };
  }
  const srcShape = srcShapes.out[srcIdx]!;
  const dstShape = dstShapes.in[dstIdx]!;
  if (!shapeEquals(srcShape, dstShape)) {
    return {
      ok: false,
      reason:
        `Port shape mismatch: ${src.id}.out[${srcIdx}] = ${formatShape(srcShape)} → ` +
        `${dst.id}.in[${dstIdx}] = ${formatShape(dstShape)}. ` +
        `Use Mux/Demux to adapt scalar/vector ports.`,
    };
  }
  return { ok: true };
}

/**
 * registry list を type_path 索引可能な Map に変換する。
 * `useMemo` でキャッシュ推奨。
 */
export function indexRegistry(
  registry: readonly BlockMetadata[],
): Map<string, BlockMetadata> {
  const map = new Map<string, BlockMetadata>();
  for (const m of registry) {
    map.set(m.type_path, m);
  }
  return map;
}
