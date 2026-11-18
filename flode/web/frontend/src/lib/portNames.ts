// ADR-0087 論点 3-C: 接続元ポート名 (ブロックが持つ出力ポートの名前) を 1 か所で引く。
//
// 出どころは 3 系統 (F-16):
// - ユーザーブロック: registry の ``output_names`` (dynamic_ports なら引数ごとに解決した名前)
// - Python 関数ブロック: introspect の ``output_names`` (非同期 cache、未解決なら無し)
// - Subsystem: 内部 Outport の id を ``port_idx`` 順 (既定 id ``Outport_0`` も名前として使う)
//
// 既存の描画コード (BlockNodeView / diagramConverter) はまだこれを使っていない (表示の回帰を
// 避けるため、寄せるのは別の整理として行う)。

import type { BlockEntry } from "../types/api";
import { getNumberParam, OUTPORT_TYPE, PYTHON_FUNCTION_TYPE } from "./blockTypes";
import { getCachedPythonSpec } from "./pythonFunctionSpec";
import { effectiveUserBlockPorts } from "./userBlockPorts";
import { userBlockMetaOf, type RegistryIndex } from "./userBlockModel";

/** 空文字は「名前なし」。 */
function nonEmpty(name: unknown): string | null {
  return typeof name === "string" && name !== "" ? name : null;
}

/**
 * ブロックの出力ポート ``outIdx`` の名前。
 *
 * @param block - 接続元ブロック。
 * @param outIdx - 出力ポート番号。
 * @param registry - block registry の索引 (未取得なら ``undefined`` = ユーザーブロック名なし)。
 * @returns ポート名 (無い・空なら ``null``)。
 */
export function portNameOf(
  block: BlockEntry,
  outIdx: number,
  registry: RegistryIndex | undefined,
): string | null {
  const params = (block.params ?? {}) as Record<string, unknown>;
  const meta = userBlockMetaOf(block.type, registry);
  if (meta !== undefined) {
    return nonEmpty(effectiveUserBlockPorts(meta, params).outputNames[outIdx]);
  }
  if (block.type === PYTHON_FUNCTION_TYPE) {
    const spec = getCachedPythonSpec(params.code);
    if (spec === undefined || !spec.resolved) return null;
    return nonEmpty(spec.output_names[outIdx]);
  }
  const inner = params.blocks;
  if (Array.isArray(inner)) {
    for (const raw of inner as unknown[]) {
      if (typeof raw !== "object" || raw === null) continue;
      const b = raw as BlockEntry;
      if (b.type !== OUTPORT_TYPE) continue;
      const idx = getNumberParam((b.params ?? {}) as Record<string, unknown>, "port_idx", -1);
      if (idx === outIdx) return nonEmpty(b.id);
    }
  }
  return null;
}
