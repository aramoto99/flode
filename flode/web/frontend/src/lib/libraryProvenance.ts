// ADR-0080 §A3: ライブラリ由来 (provenance) の組み立てと、ライブラリエントリから
// 配置用ブロック entry を作る純関数。由来は情報であり、モデルの意味論には影響しない。

import type {
  BlockEntry,
  BlockProvenance,
  LibraryEntryDetail,
  LibraryEntryMetadata,
  LibraryMetadata,
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

// ---------------------------------------------------------------------------
// 由来の解決 (SPEC-0032 §1.4-4 / ADR-0080 §A3-3)
// ---------------------------------------------------------------------------

/**
 * モデルファイルから読んだ値を由来として検証する。モデルファイルは他人から受け取り
 * うるので、形が合わないもの (型違い・空文字・revision が正の整数でない) は由来なし
 * として扱う (エラーにはしない。由来は情報であり、読込・実行を妨げない)。
 *
 * @param raw ブロック entry の ``provenance`` の値。
 * @returns 検証済みの由来。形が合わなければ ``null``。
 */
export function readProvenance(raw: unknown): BlockProvenance | null {
  if (typeof raw !== "object" || raw === null) return null;
  // 自身のプロパティだけを読む (``__proto__`` 経由で継承した値を由来として扱わない)
  const own = (key: string): unknown =>
    Object.prototype.hasOwnProperty.call(raw, key)
      ? (raw as Record<string, unknown>)[key]
      : undefined;
  const library = own("library");
  const uid = own("library_uid");
  const entry = own("entry");
  const revision = own("revision");
  if (typeof library !== "string" || library === "") return null;
  if (typeof entry !== "string" || entry === "") return null;
  // 安全な整数の範囲外 (1e308 等) は revision として扱わない
  if (typeof revision !== "number" || !Number.isSafeInteger(revision) || revision < 1) {
    return null;
  }
  if (uid !== undefined && (typeof uid !== "string" || uid === "")) return null;
  return buildProvenance(library, uid, entry, revision);
}

/** 由来の解決に使う、ライブラリ一覧の索引 (一覧が変わるたびに 1 回だけ作る)。 */
export interface LibraryIndex {
  byUid: ReadonlyMap<string, IndexedLibrary>;
  byName: ReadonlyMap<string, IndexedLibrary>;
}

interface IndexedLibrary {
  library: LibraryMetadata;
  entries: ReadonlyMap<string, LibraryEntryMetadata>;
}

/** ライブラリ一覧から索引を作る (ブロックごとに一覧を線形探索しないため)。 */
export function buildLibraryIndex(libraries: readonly LibraryMetadata[]): LibraryIndex {
  const byUid = new Map<string, IndexedLibrary>();
  const byName = new Map<string, IndexedLibrary>();
  for (const library of libraries) {
    const indexed: IndexedLibrary = {
      library,
      entries: new Map(library.entries.map((e) => [e.id, e])),
    };
    byName.set(library.name, indexed);
    // uid は registry 内で一意 (ADR-0080 Amendments 2)。万一重複していたら先勝ち
    if (library.uid && !byUid.has(library.uid)) byUid.set(library.uid, indexed);
  }
  return { byUid, byName };
}

/**
 * 由来の状態。
 * - ``none``: 由来を持たない (または形が不正)
 * - ``missing``: 由来先のライブラリまたはエントリが見つからない (エラーではない)
 * - ``current``: 由来の revision = ライブラリの revision
 * - ``update``: ライブラリの方が新しい (更新あり)
 * - ``ahead``: 由来の方が新しい (ライブラリを古い版に戻した等。SPEC-0032 §1.8:
 *   「ライブラリより新しい版」と表示し、差し替えは可能)
 */
export type ProvenanceStatus =
  | { kind: "none" }
  | { kind: "missing"; provenance: BlockProvenance }
  | {
      kind: "current" | "update" | "ahead";
      provenance: BlockProvenance;
      library: LibraryMetadata;
      entry: LibraryEntryMetadata;
    };

/**
 * ブロックの由来を、ライブラリ一覧の索引に突き合わせて解決する。
 *
 * 突合規則 (ADR-0080 §A3-3): 由来に ``library_uid`` があれば **uid が一致する
 * ライブラリのみ**を由来先とみなす (名前は問わない = 書き出しで改名されたライブラリも
 * 追える。名前が同じでも uid が違えば別物 = 他人の ``user/pid`` を自分のものと誤認
 * しない)。``library_uid`` が無ければ名前で突合する。
 *
 * @param rawProvenance ブロック entry の ``provenance`` (未検証でよい)。
 * @param index ``buildLibraryIndex`` の結果。
 */
export function resolveProvenance(
  rawProvenance: unknown,
  index: LibraryIndex,
): ProvenanceStatus {
  const provenance = readProvenance(rawProvenance);
  if (provenance === null) return { kind: "none" };
  const indexed =
    provenance.library_uid !== undefined
      ? index.byUid.get(provenance.library_uid)
      : index.byName.get(provenance.library);
  const entry = indexed?.entries.get(provenance.entry);
  if (indexed === undefined || entry === undefined) {
    return { kind: "missing", provenance };
  }
  const kind =
    entry.revision > provenance.revision
      ? "update"
      : entry.revision < provenance.revision
        ? "ahead"
        : "current";
  return { kind, provenance, library: indexed.library, entry };
}
