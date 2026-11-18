// ADR-0021 §(2): editingPath で path 先の Subsystem 内部に潜り、blocks/connections/layout
// を取り出す純関数。`applyAtPath` で immutable に書き換える。

import type {
  BlockEntry,
  BranchWaypoint,
  BranchWaypointDict,
  ConnectionEntry,
  FlwModel,
  LayoutDict,
} from "../types/api";

export interface BlockListView {
  blocks: BlockEntry[];
  connections: ConnectionEntry[];
  layout: LayoutDict;
}

/**
 * `path = []` のとき top-level、`path = ["sub1"]` のとき `sub1` の内部、というふうに
 * 階層を辿って blocks/connections/layout を返す。
 *
 * @throws path 解決中に block が見つからない / 非 Subsystem を辿ろうとした場合に Error。
 */
export function resolveBlocksAtPath(
  model: FlwModel,
  path: readonly string[],
): BlockListView {
  let blocks: BlockEntry[] = model.blocks;
  let connections: ConnectionEntry[] = model.connections;
  let layout: LayoutDict = model.layout ?? {};
  for (const segId of path) {
    const sub = blocks.find((b) => b.id === segId);
    if (!sub) {
      throw new Error(`Subsystem path segment not found: ${segId}`);
    }
    const params = sub.params as Record<string, unknown>;
    // Subsystem は ``blocks`` キーを持つ。registry default = None で生成された Subsystem
    // は ``blocks: null`` を持つことがあるので、キーが存在すれば null/undefined を空配列
    // として縮退する。キーが存在しない (= 真の非 Subsystem) なら従来通り throw。
    if (!("blocks" in params)) {
      throw new Error(`Block ${segId} is not a Subsystem (no params.blocks)`);
    }
    const innerBlocks = params.blocks;
    const innerConnections = params.connections;
    const innerLayout = params.layout;
    if (innerBlocks !== undefined && innerBlocks !== null && !Array.isArray(innerBlocks)) {
      throw new Error(`Block ${segId} is not a Subsystem (params.blocks is not array)`);
    }
    blocks = (innerBlocks as BlockEntry[] | null | undefined) ?? [];
    connections = (innerConnections as ConnectionEntry[] | null | undefined) ?? [];
    layout = (innerLayout as LayoutDict | null | undefined) ?? {};
  }
  return { blocks, connections, layout };
}

/**
 * `path` 先の view を `fn` で書き換えた新しい FlwModel を返す。immutable update。
 *
 * @throws resolveBlocksAtPath と同じ条件で Error。
 */
export function applyAtPath(
  model: FlwModel,
  path: readonly string[],
  fn: (view: BlockListView) => BlockListView,
): FlwModel {
  if (path.length === 0) {
    const next = fn({
      blocks: model.blocks,
      connections: model.connections,
      layout: model.layout ?? {},
    });
    return {
      ...model,
      blocks: next.blocks,
      connections: next.connections,
      layout: next.layout,
    };
  }
  const [head, ...rest] = path;
  const idx = model.blocks.findIndex((b) => b.id === head);
  if (idx < 0) {
    throw new Error(`Subsystem path segment not found: ${head}`);
  }
  const sub = model.blocks[idx]!;
  const innerParams = sub.params as Record<string, unknown>;
  // null/undefined を空 array/dict として安全に縮退 (resolveBlocksAtPath と同様)
  const innerView: BlockListView = {
    blocks: (innerParams.blocks as BlockEntry[] | null | undefined) ?? [],
    connections: (innerParams.connections as ConnectionEntry[] | null | undefined) ?? [],
    layout: (innerParams.layout as LayoutDict | null | undefined) ?? {},
  };
  // Recurse into inner Subsystem at rest path
  const innerModel: FlwModel = {
    schema_version: model.schema_version,
    simulator: model.simulator,
    blocks: innerView.blocks,
    connections: innerView.connections,
    layout: innerView.layout,
  };
  const updatedInner = applyAtPath(innerModel, rest, fn);
  const newSub: BlockEntry = {
    ...sub,
    params: {
      ...innerParams,
      blocks: updatedInner.blocks,
      connections: updatedInner.connections,
      ...(updatedInner.layout && Object.keys(updatedInner.layout).length > 0
        ? { layout: updatedInner.layout }
        : {}),
    },
  };
  const newBlocks = [...model.blocks];
  newBlocks[idx] = newSub;
  return { ...model, blocks: newBlocks };
}

/**
 * path 先の指定 id の block を返す。見つからなければ undefined。
 */
export function findBlockAtPath(
  model: FlwModel,
  path: readonly string[],
  id: string,
): BlockEntry | undefined {
  const view = resolveBlocksAtPath(model, path);
  return view.blocks.find((b) => b.id === id);
}

// ---------------------------------------------------------------------------
// ADR-0057: 手動 branch waypoint の scope-aware アクセス。
//
// root scope は ``model.branch_waypoints``、Subsystem scope は当該 Subsystem の
// ``params.branch_waypoints`` に置く (= ADR-0020 の layout 再帰方針に揃える)。
// layout の ``resolveBlocksAtPath`` / ``applyAtPath`` とは別経路だが、未知キーの
// 保持は ``applyAtPath`` の ``{...innerParams}`` spread で自動的に効くため、本
// helper は waypoint の読み書きのみ担う (= connections / layout は触らない)。
// ---------------------------------------------------------------------------

/**
 * ``path`` 先の scope の branch_waypoints を返す。欠落時は空 dict。
 *
 * @throws resolveBlocksAtPath と同じ条件 (path 解決失敗) で Error。
 */
export function resolveBranchWaypointsAtPath(
  model: FlwModel,
  path: readonly string[],
): BranchWaypointDict {
  return resolveScopeDictAtPath<BranchWaypoint>(model, path, "branch_waypoints");
}

/**
 * ``path`` 先の scope の branch_waypoints を ``fn`` で書き換えた新しい FlwModel を
 * 返す。immutable update。空 dict になったらキーごと削除する (= JSON をクリーンに
 * 保つ、layout / scope_settings と同方針)。connections / layout / blocks は不変。
 *
 * @throws path 解決失敗時に Error。
 */
export function applyBranchWaypointsAtPath(
  model: FlwModel,
  path: readonly string[],
  fn: (waypoints: BranchWaypointDict) => BranchWaypointDict,
): FlwModel {
  return applyScopeDictAtPath<BranchWaypoint>(model, path, "branch_waypoints", fn);
}

/**
 * スコープごとに置く ``"<src_id>:<src_idx>"`` キーの dict の名前 (ADR-0057 / ADR-0087)。
 * 最上位はモデルの同名キー、Subsystem の中はその Subsystem の ``params`` の同名キー。
 */
export type ScopeDictKey = "branch_waypoints" | "signal_names";

/** path の 1 段を辿る (Subsystem の ``params`` を返す)。 */
function descendScope(blocks: readonly BlockEntry[], segId: string): Record<string, unknown> {
  const sub = blocks.find((b) => b.id === segId);
  if (!sub) {
    throw new Error(`Subsystem path segment not found: ${segId}`);
  }
  const params = sub.params as Record<string, unknown>;
  if (!("blocks" in params)) {
    throw new Error(`Block ${segId} is not a Subsystem (no params.blocks)`);
  }
  return params;
}

/**
 * ``path`` 先の scope の ``key`` の dict を返す。欠落時は空 dict。
 * 値の検証はしない (信号名は ``readSignalNames`` で検証して読む)。
 *
 * @param model - モデル。
 * @param path - スコープの path (``[]`` = 最上位)。
 * @param key - dict の名前。
 * @throws resolveBlocksAtPath と同じ条件 (path 解決失敗) で Error。
 */
export function resolveScopeDictAtPath<T>(
  model: FlwModel,
  path: readonly string[],
  key: ScopeDictKey,
): Record<string, T> {
  let scope = model as unknown as Record<string, unknown>;
  for (const segId of path) {
    const blocks = (scope.blocks as BlockEntry[] | null | undefined) ?? [];
    scope = descendScope(blocks, segId);
  }
  return (scope[key] as Record<string, T> | null | undefined) ?? {};
}

/**
 * ``path`` 先の scope の ``key`` の dict を ``fn`` で書き換えた新しい FlwModel を返す
 * (immutable update)。空 dict になったらキーごと削除する。``fn`` が同じ参照を返し、
 * キーを消す必要も無ければ ``model`` をそのまま返す。他のキー・params は保持する。
 *
 * @param model - モデル。
 * @param path - スコープの path (``[]`` = 最上位)。
 * @param key - dict の名前。
 * @param fn - 今の dict (欠落時は空 dict) を受け取り新しい dict を返す関数。
 * @throws path 解決失敗時に Error。
 */
export function applyScopeDictAtPath<T>(
  model: FlwModel,
  path: readonly string[],
  key: ScopeDictKey,
  fn: (dict: Record<string, T>) => Record<string, T>,
): FlwModel {
  const updated = applyScopeDict(model as unknown as Record<string, unknown>, path, key, fn);
  return updated as unknown as FlwModel;
}

function applyScopeDict<T>(
  scope: Record<string, unknown>,
  path: readonly string[],
  key: ScopeDictKey,
  fn: (dict: Record<string, T>) => Record<string, T>,
): Record<string, unknown> {
  if (path.length === 0) {
    const raw = scope[key] as Record<string, T> | null | undefined;
    const cur = raw ?? {};
    const next = fn(cur);
    const empty = Object.keys(next).length === 0;
    if (next === cur && (empty ? raw === undefined : true)) return scope;
    const out = { ...scope };
    if (empty) {
      delete out[key];
    } else {
      out[key] = next;
    }
    return out;
  }
  const [head, ...rest] = path;
  const blocks = (scope.blocks as BlockEntry[] | null | undefined) ?? [];
  const idx = blocks.findIndex((b) => b.id === head);
  if (idx < 0) {
    throw new Error(`Subsystem path segment not found: ${head}`);
  }
  const sub = blocks[idx]!;
  const innerParams = descendScope(blocks, head!);
  const newParams = applyScopeDict(innerParams, rest, key, fn);
  if (newParams === innerParams) return scope;
  const newBlocks = [...blocks];
  newBlocks[idx] = { ...sub, params: newParams };
  return { ...scope, blocks: newBlocks };
}

/**
 * 与えられた scope の connections に対し、孤児となった branch_waypoint を除いた
 * dict を返す (ADR-0057 §(5) 孤児掃除)。
 *
 * 手動分岐点は ``(source, sourceHandle)`` に**2 本以上**の枝があって初めて成立する
 * ため、合成キー ``"<src>:<src_idx>"`` のグループが 2 本未満になった waypoint を
 * drop する。元 dict は変更しない (pure)。
 *
 * ADR-0057 §(5) の孤児掃除 3 層のうち本 helper は **操作時** (connection / block
 * 削除) に使う。**load 時**は描画側 (DiagramCanvas / resolveJunctions) が枝 2 本
 * 未満のグループを楽観無視するため孤児は描画されず、次の操作で本 helper が drop
 * する。**save 時の防御的再帰掃除** (全 subsystem scope を走査) は未実装 (= 操作時 +
 * load 楽観無視で正しさは担保され、残りは JSON をクリーンに保つ cosmetic な層)。
 *
 * @param connections 対象 scope の connection 一覧。
 * @param waypoints 対象 scope の branch_waypoints。
 * @returns 2 本以上のグループに対応するキーだけ残した新しい dict。
 */
export function pruneBranchWaypoints(
  connections: readonly ConnectionEntry[],
  waypoints: BranchWaypointDict,
): BranchWaypointDict {
  const counts = new Map<string, number>();
  for (const c of connections) {
    const key = `${c.src}:${c.src_idx}`;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const out: BranchWaypointDict = {};
  for (const [key, pos] of Object.entries(waypoints)) {
    if ((counts.get(key) ?? 0) >= 2) out[key] = pos;
  }
  return out;
}
