// ADR-0021 §(2): editingPath で path 先の Subsystem 内部に潜り、blocks/connections/layout
// を取り出す純関数。`applyAtPath` で immutable に書き換える。

import type {
  BlockEntry,
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
    const innerBlocks = (sub.params as Record<string, unknown>).blocks;
    const innerConnections = (sub.params as Record<string, unknown>).connections;
    const innerLayout = (sub.params as Record<string, unknown>).layout;
    if (!Array.isArray(innerBlocks)) {
      throw new Error(`Block ${segId} is not a Subsystem (no params.blocks)`);
    }
    blocks = innerBlocks as BlockEntry[];
    connections = (innerConnections as ConnectionEntry[]) ?? [];
    layout = (innerLayout as LayoutDict | undefined) ?? {};
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
  const innerView: BlockListView = {
    blocks: (innerParams.blocks as BlockEntry[] | undefined) ?? [],
    connections: (innerParams.connections as ConnectionEntry[] | undefined) ?? [],
    layout: (innerParams.layout as LayoutDict | undefined) ?? {},
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
