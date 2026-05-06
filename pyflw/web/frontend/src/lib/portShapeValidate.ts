// ADR-0019 §(6): port shape の整合性をフロントで pre-validate するヘルパ。
// strict 一致 (broadcasting なし、ADR-0017 §(4))。

import type { BlockEntry, BlockMetadata } from "../types/api";

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
 * 簡易版: build 時に server が `resolve-port-shapes` で確定した port_shapes は
 * BlockEntry には載らない (= JSON 永続化対象外)。GUI は registry のデフォルトを
 * 使用し、param 変更で port 数が変わるブロックでは resolve-port-shapes を呼んで
 * 補正する (ADR-0019 §6.1)。本ヘルパは default を返すだけ。
 */
export function getDefaultPortShapes(
  block: BlockEntry,
  registry: ReadonlyMap<string, BlockMetadata>,
): { in: number[][]; out: number[][] } {
  const meta = registry.get(block.type);
  if (!meta) {
    return { in: [], out: [] };
  }
  return {
    in: meta.port_shapes_in_default,
    out: meta.port_shapes_out_default,
  };
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
