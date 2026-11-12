// ADR-0080 §A3: ライブラリ由来 (provenance) の組み立てと、ライブラリエントリから
// 配置用ブロック entry を作る純関数。由来は情報であり、モデルの意味論には影響しない。

import type {
  BlockEntry,
  BlockProvenance,
  LibraryEntryDetail,
} from "../types/api";
import { PYTHON_FUNCTION_TYPE, SUBSYSTEM_TYPE } from "./blockTypes";
import { generateIdFromName } from "./idGenerator";

/**
 * 由来を組み立てる。``libraryUid`` が無い (uid を持たないライブラリ) ときは
 * ``library_uid`` を**キーごと省略**する (空文字や null を書かない、ADR-0080 §A3-1)。
 */
export function buildProvenance(
  library: string,
  libraryUid: string | null | undefined,
  entry: string,
  revision: number,
): BlockProvenance {
  return {
    library,
    ...(libraryUid ? { library_uid: libraryUid } : {}),
    entry,
    revision,
  };
}

/**
 * ライブラリエントリの詳細レスポンスから、キャンバスに置くブロック entry を作る。
 *
 * - id はエントリの表示名由来 (SPEC-0032 §1.4-2、規則に通らなければ型名由来)。
 * - ``params`` は本体をそのまま使う (= ``Block.to_dict()`` の出力と byte-identical)。
 * - 由来の revision / uid は一覧キャッシュではなく、本体と同じ詳細レスポンスから取る
 *   (ADR-0080 §A5: 一覧が古くても本体と版が食い違わない)。
 *
 * @param libraryName drop されたライブラリの名前。
 * @param detail ``GET /libraries/{lib}/{entry}`` の応答。
 * @param existingIds 配置先スコープの既存 block id 集合。
 */
export function blockFromLibraryEntry(
  libraryName: string,
  detail: LibraryEntryDetail,
  existingIds: ReadonlySet<string>,
): BlockEntry {
  return {
    id: generateIdFromName(
      detail.display_name || detail.id,
      detail.block.type,
      existingIds,
    ),
    type: detail.block.type,
    params: detail.block.params,
    provenance: buildProvenance(
      libraryName,
      detail.library_uid,
      detail.id,
      detail.revision,
    ),
  };
}

/**
 * ライブラリに登録できる種別か (SPEC-0032 §1.2-1: Subsystem 系と PythonFunction)。
 * Triggered / Enabled は単一の Subsystem クラス + 内部制御ブロックなので型は同じ。
 * 最終判定はサーバ (クラス解決 + ``issubclass``) が行う。
 */
export function isRegistrableBlockType(typePath: string): boolean {
  return typePath === SUBSYSTEM_TYPE || typePath === PYTHON_FUNCTION_TYPE;
}
