// ADR-0056 follow-up: Log tab のエラーメッセージから対象ブロックへジャンプする
// ために、block_id からサブシステム階層の drilldown パスを逆引きする。
//
// pathResolver.ts の ``resolveBlocksAtPath`` と同じ Subsystem 構造
// (= ``block.params.blocks`` に子ブロック配列) を前提に DFS する。

import type { BlockEntry, FlwModel } from "../types/api";

/**
 * `blockId` への drilldown パス (= 親 Subsystem の id 列) を返す。
 *
 * - top-level に存在: `[]`
 * - `sub1` 内: `["sub1"]`、`sub1 > sub2` 内: `["sub1", "sub2"]`
 * - 見つからない (= 別モデルに切替後など): `null`
 *
 * 返すパスは ``editingPath`` にそのままセットでき、対象ブロック自体の id は
 * 含まない (= drilldown 先の view にそのブロックが見える状態になる)。
 *
 * @param model 探索対象モデル。
 * @param blockId 探したいブロック ID。
 * @returns drilldown パス、または `null`。
 */
export function findBlockPath(
  model: FlwModel,
  blockId: string,
): string[] | null {
  const walk = (blocks: BlockEntry[], prefix: string[]): string[] | null => {
    for (const b of blocks) {
      if (b.id === blockId) return prefix;
      const params = b.params as Record<string, unknown> | undefined;
      const inner = params?.blocks;
      if (Array.isArray(inner) && b.id != null) {
        const found = walk(inner as BlockEntry[], [...prefix, b.id]);
        if (found !== null) return found;
      }
    }
    return null;
  };
  return walk(model.blocks, []);
}
