// ADR-0080 §A7-3 / SPEC-0032 §1.4-6: ライブラリの現在の版への差し替えの実行手順。
//
//   本体の取得 → PythonFunction の静的解析の取得 → 互換判定 → 適用直前の再確認 →
//   ``applyEditingModel`` 1 回 (= undo 1 回で完全に戻る)
//
// 確認ダイアログと結果の表示は呼び出し側 (Inspector) が行う。本体の取得は非同期
// なので、その間にファイル・階層・対象ブロックが変わっていたら何もしない。

import { getLibraryEntry } from "../api/client";
import { useAppStore } from "../store/appStore";
import type { BlockEntry, BlockProvenance } from "../types/api";
import { PYTHON_FUNCTION_TYPE } from "./blockTypes";
import { buildProvenance, readProvenance } from "./libraryProvenance";
import {
  buildReplacementBlock,
  carryOverValues,
  checkReplacementCompatibility,
  replaceBlockInModel,
  type ReplacementIssue,
} from "./libraryReplacement";
import { resolveBlocksAtPath } from "./pathResolver";
import { ensurePythonSpecs, getCachedPythonSpec } from "./pythonFunctionSpec";

/** 差し替えの対象 (確認ダイアログを出した時点の snapshot)。 */
export interface ReplacementTarget {
  /** 開いているファイル。 */
  filePath: string | null;
  /** 対象ブロックがある階層。 */
  path: readonly string[];
  /** 対象ブロックの id。 */
  blockId: string;
  /** 対象ブロックの由来 (適用直前に同じであることを確かめる)。 */
  provenance: BlockProvenance;
  /** 由来先ライブラリの**現在の名前** (uid 突合で解決したもの。由来の名前とは限らない)。 */
  libraryName: string;
}

/** 差し替えの結果。 */
export type ReplacementOutcome =
  | {
      status: "applied";
      /** 差し替え後の revision。 */
      revision: number;
      /** 引き継げなかったパラメータ名。 */
      notCarried: string[];
      /** 名前が変わった・無くなったポート。 */
      portNameChanges: string[];
    }
  /** 既存の接続を保てない等で拒否した (モデルは変えていない)。 */
  | { status: "incompatible"; issues: ReplacementIssue[] }
  /** 取得中にファイル・階層・対象ブロックが変わっていた (何もしていない)。 */
  | { status: "stale" }
  /** 本体の取得に失敗した (何もしていない)。 */
  | { status: "failed"; error: unknown };

/** 対象が snapshot のまま存在すればそのブロックを返す (崩れていれば ``null``)。 */
function findUnchangedTarget(target: ReplacementTarget): BlockEntry | null {
  const state = useAppStore.getState();
  if (state.selectedFilePath !== target.filePath || !state.editingModel) return null;
  if (JSON.stringify(state.editingPath) !== JSON.stringify(target.path)) return null;
  let block: BlockEntry | undefined;
  try {
    block = resolveBlocksAtPath(state.editingModel, target.path).blocks.find(
      (b) => b.id === target.blockId,
    );
  } catch {
    return null;
  }
  if (block === undefined) return null;
  // 同じ id でも由来が違えば別のブロック (削除して作り直した等)
  // (キー順の違いで誤判定しないよう、どちらも ``readProvenance`` の正規形で比べる)
  if (
    JSON.stringify(readProvenance(block.provenance)) !==
    JSON.stringify(readProvenance(target.provenance))
  ) {
    return null;
  }
  return block;
}

/**
 * 対象ブロックを、由来先ライブラリの現在の版で差し替える。
 *
 * 成功時はモデルを ``applyEditingModel`` 1 回で更新する (undo 1 回で戻る、dirty)。
 * それ以外の結果ではモデルに触れない。
 *
 * @param target 確認ダイアログを出した時点の対象。
 */
export async function replaceBlockFromLibrary(
  target: ReplacementTarget,
): Promise<ReplacementOutcome> {
  const before = findUnchangedTarget(target);
  if (before === null) return { status: "stale" };

  let detail;
  try {
    detail = await getLibraryEntry(target.libraryName, target.provenance.entry);
  } catch (error) {
    return { status: "failed", error };
  }
  // 由来が指す uid と、取得した本体のライブラリの uid が違えば別のライブラリ
  // (確認後に同名のライブラリへ入れ替わった等)。確認した相手ではないので何もしない
  if (
    target.provenance.library_uid !== undefined &&
    detail.library_uid !== target.provenance.library_uid
  ) {
    return { status: "stale" };
  }
  const newBody = detail.block;

  // 判定の前に、対象ブロック自身が PythonFunction なら新旧コードの静的解析結果を
  // 取得しておく (未取得の既定値 1 in / 1 out で判定しないため、ADR-0080 §A7-1)。
  // 外面のポートを決めるのは対象自身のコードだけなので、Subsystem 内部の
  // PythonFunction は取得しない。取得できたかどうかは互換判定が新旧別に報告する。
  const codes = [before, newBody]
    .filter((b) => b.type === PYTHON_FUNCTION_TYPE)
    .map((b) => b.params.code)
    .filter((code): code is string => typeof code === "string");
  if (codes.length > 0) {
    try {
      await ensurePythonSpecs(codes);
    } catch {
      // 通信失敗。未取得のまま互換判定に進み、そこで拒否される
    }
  }

  // --- ここから同期: 再確認 → 判定 → 適用の間に他の編集は割り込まない ---
  const current = findUnchangedTarget(target);
  if (current === null) return { status: "stale" };
  const state = useAppStore.getState();
  const model = state.editingModel;
  if (!model) return { status: "stale" };
  const { connections } = resolveBlocksAtPath(model, target.path);

  const compatibility = checkReplacementCompatibility(
    current,
    newBody,
    connections,
    getCachedPythonSpec,
  );
  if (!compatibility.ok) return { status: "incompatible", issues: compatibility.issues };

  const { params, notCarried } = carryOverValues(current, newBody, getCachedPythonSpec);
  // 由来は一覧ではなく、本体と同じ詳細レスポンスの値で作る (ADR-0080 §A5)
  const replacement = buildReplacementBlock(
    current,
    newBody,
    params,
    buildProvenance(target.libraryName, detail.library_uid, detail.id, detail.revision),
  );
  state.applyEditingModel((m) =>
    replaceBlockInModel(m, target.path, target.blockId, replacement, compatibility.nOutputs),
  );
  return {
    status: "applied",
    revision: detail.revision,
    notCarried,
    portNameChanges: compatibility.portNameChanges,
  };
}
