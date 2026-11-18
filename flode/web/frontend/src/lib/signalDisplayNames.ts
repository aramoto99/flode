// ADR-0087 論点 3 / SPEC-0038 §4: Scope の列ごとの表示名を決める (凡例・画像コピーの凡例・
// Scope 設定ダイアログの信号行が同じ結果を使う)。
//
// 規則 (列ごと): 信号名 > 接続元ポート名 > (接続元が Mux なら各入力をたどる) > 既定名。
// ベクトル・行列は backend の列ラベル (``_expand_column_labels``) と同じく ``名前[k]`` /
// ``名前[i,j]`` (C order) に展開する。列の形は信号面解決 (resolve-dtypes) の shape を使い、
// 形が分からないポートはスカラとみなす。列数 (Σ 要素数) が実際の列数と合わなければ全列を
// 既定名にする (index 突合の安全策)。

import { useMemo, useRef, useSyncExternalStore } from "react";

import { useAppStore } from "../store/appStore";
import type { BlockEntry, BlockRegistryResponse, ConnectionEntry } from "../types/api";
import { getNumberParam } from "./blockTypes";
import { shapeForPort, useDtypeResolution } from "./dtypeResolution";
import { portNameOf } from "./portNames";
import { indexRegistry } from "./portShapeValidate";
import { getPythonSpecVersion, subscribePythonSpecs } from "./pythonFunctionSpec";
import { queryClient } from "./queryClient";
import { BLOCKS_REGISTRY_QUERY_KEY } from "./queryKeys";
import { readSignalNames } from "./signalNames";
import { getUserBlockPortsVersion, subscribeUserBlockPorts } from "./userBlockPorts";
import type { RegistryIndex } from "./userBlockModel";

/** Mux の型パス。 */
export const MUX_TYPE = "flode.blocks.routing.Mux";
/** Mux をたどる深さの上限 (循環・暴走の防止)。 */
export const MAX_MUX_DEPTH = 32;

/** 表示名を決めるのに使うスコープ (最上位のモデル or Subsystem の中身)。 */
export interface LabelScope {
  blocks: readonly BlockEntry[];
  connections: readonly ConnectionEntry[];
  /** そのスコープの ``signal_names`` (検証前の生の値)。 */
  signal_names?: unknown;
}

/** ``deriveScopeColumnLabels`` の入力。 */
export interface ScopeColumnLabelInput {
  scope: LabelScope;
  scopeId: string;
  /** 列数 (``buffer.n_signals``)。 */
  nColumns: number;
  /** 解決済みの shape (未解決は ``null``)。 */
  shapeOf: (blockId: string, direction: "in" | "out", portIndex: number) => number[] | null;
  /** 接続元ポート名 (無ければ ``null``)。 */
  portNameOf: (block: BlockEntry, outIdx: number) => string | null;
}

/**
 * 既定名の列 (今までの凡例名: 1 列なら ``scopeId``、複数なら ``scopeId[i]``)。
 *
 * @param scopeId - Scope の id。
 * @param nColumns - 列数。
 */
export function defaultScopeColumnLabels(scopeId: string, nColumns: number): string[] {
  return Array.from({ length: nColumns }, (_, i) =>
    nColumns === 1 ? scopeId : `${scopeId}[${i}]`,
  );
}

function widthOf(shape: readonly number[] | null): number {
  return (shape ?? []).reduce((acc, n) => acc * n, 1);
}

/** ``base`` を shape で展開する (``()`` → ``base``、他は C order の ``base[i,j]``)。 */
export function expandLabel(base: string, shape: readonly number[] | null): string[] {
  if (shape === null || shape.length === 0) return [base];
  const total = widthOf(shape);
  const out: string[] = [];
  const index = new Array<number>(shape.length).fill(0);
  for (let n = 0; n < total; n++) {
    out.push(`${base}[${index.join(",")}]`);
    for (let d = shape.length - 1; d >= 0; d--) {
      index[d]! += 1;
      if (index[d]! < shape[d]!) break;
      index[d] = 0;
    }
  }
  return out;
}

/** 入力ポート数 = 配線の ``dst_idx`` の最大 + 1 と ``params[countParam]`` の大きい方。 */
function inputPortCount(
  block: BlockEntry,
  connections: readonly ConnectionEntry[],
  countParam: string,
  fallback: number,
): number {
  let n = getNumberParam((block.params ?? {}) as Record<string, unknown>, countParam, fallback);
  for (const c of connections) {
    if (c.dst === block.id) n = Math.max(n, c.dst_idx + 1);
  }
  return Math.max(0, Math.floor(n));
}

/**
 * Scope の列ごとの表示名を決める (ADR-0087 論点 3-C)。
 *
 * @param input - スコープのモデル・Scope の id・列数・shape と接続元ポート名の引き方。
 * @returns 列ごとの表示名 (長さ = ``nColumns``)。
 */
export function deriveScopeColumnLabels(input: ScopeColumnLabelInput): string[] {
  const { scope, scopeId, nColumns, shapeOf } = input;
  const defaults = defaultScopeColumnLabels(scopeId, nColumns);
  if (nColumns <= 0) return defaults;
  const scopeBlock = scope.blocks.find((b) => b.id === scopeId);
  if (scopeBlock === undefined) return defaults;

  const names = readSignalNames(scope.signal_names);
  const byId = new Map(scope.blocks.map((b) => [b.id, b] as const));
  const incoming = (dst: string, dstIdx: number): ConnectionEntry | undefined =>
    scope.connections.find((c) => c.dst === dst && c.dst_idx === dstIdx);

  const nPorts = inputPortCount(scopeBlock, scope.connections, "n_inputs", 1);
  const shapes = Array.from({ length: nPorts }, (_, p) => shapeOf(scopeId, "in", p));
  const total = shapes.reduce((acc, s) => acc + widthOf(s), 0);
  if (total !== nColumns) return defaults;

  const out = [...defaults];

  /** 信号 ``src:srcIdx`` (shape ``shape``) の列を ``first`` から書く。決まらない列は既定名のまま。 */
  const fill = (
    src: string,
    srcIdx: number,
    shape: readonly number[] | null,
    first: number,
    visited: ReadonlySet<string>,
    depth: number,
  ): void => {
    const width = widthOf(shape);
    const block = byId.get(src);
    let base = names.get(`${src}:${srcIdx}`) ?? null;
    if (base === null && block !== undefined) base = input.portNameOf(block, srcIdx);
    if (base !== null && base !== "") {
      expandLabel(base, shape).forEach((label, k) => {
        if (k < width) out[first + k] = label;
      });
      return;
    }
    if (block === undefined || block.type !== MUX_TYPE) return;
    if (visited.has(src) || depth >= MAX_MUX_DEPTH) return;
    const nextVisited = new Set(visited).add(src);
    const nIn = inputPortCount(block, scope.connections, "n", 2);
    const inShapes = Array.from({ length: nIn }, (_, j) => shapeOf(src, "in", j));
    // Mux の入力の列幅の和が出力の列幅と合わなければ、たどらない (既定名)
    if (inShapes.reduce((acc, s) => acc + widthOf(s), 0) !== width) return;
    let col = first;
    inShapes.forEach((inShape, j) => {
      const c = incoming(src, j);
      if (c !== undefined) fill(c.src, c.src_idx, inShape, col, nextVisited, depth + 1);
      col += widthOf(inShape);
    });
  };

  let col = 0;
  shapes.forEach((shape, p) => {
    const c = incoming(scopeId, p);
    if (c !== undefined) fill(c.src, c.src_idx, shape, col, new Set(), 0);
    col += widthOf(shape);
  });
  return out;
}

function subscribeRegistryCache(listener: () => void): () => void {
  return queryClient.getQueryCache().subscribe(listener);
}

function registrySnapshot(): BlockRegistryResponse | undefined {
  return queryClient.getQueryData<BlockRegistryResponse>(BLOCKS_REGISTRY_QUERY_KEY);
}

/**
 * block registry の索引を react-query の cache から読む hook (取得は他の画面が行う。
 * Provider の外でも使えるよう共有の ``queryClient`` を直接購読する)。
 */
function useRegistryIndexFromCache(): RegistryIndex | undefined {
  const data = useSyncExternalStore(subscribeRegistryCache, registrySnapshot, registrySnapshot);
  return useMemo(() => (data !== undefined ? indexRegistry(data.blocks) : undefined), [data]);
}

/**
 * 最上位の Scope ``scopeId`` の列ごとの表示名を返す hook。信号名・接続・ポート名・shape が
 * 変わらない限り同じ配列 (同じ参照) を返す (``scope_batch`` ごとに作り直さない)。
 *
 * Subsystem の中の Scope は今の GUI では波形が届かない (ADR-0087 F-11) ため、最上位に
 * 見つからなければ既定名を返す。
 *
 * @param scopeId - Scope の id。
 * @param nColumns - 列数 (``buffer.n_signals``)。
 */
export function useScopeColumnLabels(scopeId: string, nColumns: number): string[] {
  const editingModel = useAppStore((s) => s.editingModel);
  const registry = useRegistryIndexFromCache();
  const resolution = useDtypeResolution();
  const pyVersion = useSyncExternalStore(
    subscribePythonSpecs,
    getPythonSpecVersion,
    getPythonSpecVersion,
  );
  const userPortsVersion = useSyncExternalStore(
    subscribeUserBlockPorts,
    getUserBlockPortsVersion,
    getUserBlockPortsVersion,
  );
  const labels = useMemo(() => {
    if (!editingModel) return defaultScopeColumnLabels(scopeId, nColumns);
    return deriveScopeColumnLabels({
      scope: editingModel,
      scopeId,
      nColumns,
      shapeOf: shapeForPort,
      portNameOf: (block, outIdx) => portNameOf(block, outIdx, registry),
    });
    // resolution / pyVersion / userPortsVersion は shapeForPort・ポート名の cache の世代
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editingModel, scopeId, nColumns, registry, resolution, pyVersion, userPortsVersion]);
  // 中身が同じなら前の配列を返す (ブロック移動など名前に関係しない編集で参照を変えない)
  const stable = useRef<string[]>(labels);
  if (
    stable.current !== labels &&
    (stable.current.length !== labels.length || stable.current.some((l, i) => l !== labels[i]))
  ) {
    stable.current = labels;
  }
  return stable.current;
}
