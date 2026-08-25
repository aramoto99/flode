// ADR-0019 §(4.4) §(9): フロント側 block ID 自動採番。
// ADR-0004 のブロック ID 規則に従う ({type_name}_{counter})。
// ADR-0071: id の文字集合は Unicode 識別子 (UAX #31 XID)。検証・正規化関数は
// Python 側 flode/core/identifiers.py の単一の写しであり、両者の等価性は
// 共有ケース表 tests/data/block_id_cases.json を読む双方のテストで担保する。

/** type_path から末尾の class 名 (= 採番 prefix) を取り出す。 */
export function typeNameFromPath(typePath: string): string {
  const parts = typePath.split(".");
  return parts[parts.length - 1] ?? "Block";
}

/**
 * ``{TypeName}_{counter}`` 形式の一意な ID を採番する。
 * 既存 IDs (= existingIds) と衝突しない最初の ``counter >= 0`` を返す。
 *
 * 通常モデルでは数百件以下の block しか持たない想定だが、念のため上限 10000 で
 * 安全側に倒す (ADR-0019 §Risks #5)。
 */
export function generateUniqueId(
  typePath: string,
  existingIds: ReadonlySet<string>,
): string {
  const typeName = typeNameFromPath(typePath);
  for (let i = 0; i < 10000; i++) {
    const candidate = `${typeName}_${i}`;
    if (!existingIds.has(candidate)) return candidate;
  }
  throw new Error(
    `Cannot allocate unique block id for ${typePath!}: 10000 candidates exhausted.`,
  );
}

/**
 * registry の `params_spec` から default params dict を組み立てる。
 *
 * `has_default=false` のパラメータには UI 上で editor を開いて入力させるため、
 * 安全な仮値 (型に応じて 0 / [] / "") を入れる。これは Phase 3 で簡易対応、
 * Phase 4+ でユーザーへの即時 modal 入力に置き換える可能性あり (Open Question)。
 *
 * is_container=true (= Subsystem) ブロックは ``blocks`` / ``connections`` フィールドを
 * 必ず空配列で持たないと、フロント側の ``resolveBlocksAtPath`` がドリルダウン時に
 * ``Array.isArray(null) === false`` で「Subsystem ではない」と誤判定する。registry の
 * Python シグネチャは ``blocks: list | None = None`` で default=null を返すため、
 * 受信側で必ず上書きする。
 */
export function buildDefaultParams(
  paramsSpec: Array<{ name: string; type: string; has_default: boolean; default: unknown }>,
  options?: { isContainer?: boolean },
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const p of paramsSpec) {
    if (p.has_default) {
      out[p.name] = p.default;
    } else {
      out[p.name] = fallbackForType(p.type);
    }
  }
  if (options?.isContainer) {
    // Subsystem 専用: 内部編集用 (ドリルダウン / 内部ブロック追加) には必ず空配列で
    // 始める。registry が null を返しても上書きする。
    if (out.blocks === null || out.blocks === undefined) out.blocks = [];
    if (out.connections === null || out.connections === undefined) out.connections = [];
  }
  return out;
}

// ---------------------------------------------------------------------------
// ADR-0071: block id の検証・正規化 (Python flode/core/identifiers.py の写し)
// ---------------------------------------------------------------------------

/** NFC 後の code point 数の上限 (ADR-0071 §(1)、Python 側 _MAX_LEN と同値)。 */
export const BLOCK_ID_MAX_LEN = 64;

/**
 * rename 検証エラーの種別 (ADR-0071 / SPEC-0022 §機能要件 3)。
 * - `not_normalized`: NFC 済でない (入口で normalizeBlockId を通せば通常発生しない)
 * - `confusable_duplicate`: NFKC fold key が既存 id と衝突 (全角/半角違い等)
 */
export type BlockIdError =
  | "empty"
  | "charset"
  | "too_long"
  | "not_normalized"
  | "duplicate"
  | "confusable_duplicate";

// UAX #31: XID_Start (XID_Continue)* + 先頭 `_` 許容 (= Python str.isidentifier())
const XID_PATTERN = /^[\p{XID_Start}_][\p{XID_Continue}]*$/u;
// ADR-0071 §(1)-(4): 多層防御の明示拒否カテゴリ (制御・書式・サロゲート・私用・
// 未割当・空白/区切り)。Python 側 _FORBIDDEN_CATEGORIES と同一
const FORBIDDEN_PATTERN = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zs}\p{Zl}\p{Zp}]/u;

// Python の hard keyword 一覧 (keyword.kwlist、Python 3.13)。warning 用途のみで
// 確定は拒否しない (ADR-0071 §(4): codegen は id を変数名に使わない)
const PYTHON_KEYWORDS = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break",
  "class", "continue", "def", "del", "elif", "else", "except", "finally",
  "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
  "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
]);

/** 保存形 (NFC) への正規化。入口層 (rename UI / store) のみが呼ぶ (ADR-0071 §(3))。 */
export function normalizeBlockId(raw: string): string {
  return raw.normalize("NFC");
}

/**
 * 重複判定専用の NFKC fold key (ADR-0071 §(2))。保存しない。
 * `Gain_1` と全角の `Gain_１`、`ソクド` と `ｿｸﾄﾞ` を同一視するための比較キー。
 */
export function foldBlockId(nfcId: string): string {
  return nfcId.normalize("NFKC");
}

/** 検証エラーの詳細。`conflictId` は duplicate 系のとき衝突相手の既存 id。 */
export interface BlockIdValidationError {
  code: BlockIdError;
  conflictId?: string;
}

/**
 * block id 候補を検証する (Python `validate_block_id` + 兄弟重複判定の写し)。
 *
 * duplicate / confusable_duplicate では衝突相手の id を `conflictId` に載せる
 * (SPEC-0022 §機能要件 9: エラー表示に衝突相手を明示する)。
 *
 * @param candidate 検証対象 (呼び出し側で `normalizeBlockId` 済みであること)。
 * @param siblingIds 同一スコープの既存 block id 集合 (NFC 形)。
 * @param currentId rename 元の id (自分自身との一致は重複とみなさない)。
 * @returns エラー詳細。OK なら null。
 */
export function validateBlockIdDetailed(
  candidate: string,
  siblingIds: ReadonlySet<string>,
  currentId?: string,
): BlockIdValidationError | null {
  if (candidate.length === 0) return { code: "empty" };
  // 巨大貼り付け対策: UTF-16 長 > 2*MAX なら code point 数も必ず > MAX なので
  // スプレッド (全 code point の配列化) を経ずに早期拒否する
  if (candidate.length > BLOCK_ID_MAX_LEN * 2) return { code: "too_long" };
  if ([...candidate].length > BLOCK_ID_MAX_LEN) return { code: "too_long" };
  if (candidate.normalize("NFC") !== candidate) return { code: "not_normalized" };
  if (!XID_PATTERN.test(candidate) || FORBIDDEN_PATTERN.test(candidate)) {
    return { code: "charset" };
  }
  if (siblingIds.has(candidate) && candidate !== currentId) {
    return { code: "duplicate", conflictId: candidate };
  }
  const fold = foldBlockId(candidate);
  for (const sibling of siblingIds) {
    if (sibling === currentId) continue;
    if (sibling !== candidate && foldBlockId(sibling) === fold) {
      return { code: "confusable_duplicate", conflictId: sibling };
    }
  }
  return null;
}

/**
 * `validateBlockIdDetailed` のエラー種別のみ版 (共有ケース表テスト等、
 * 衝突相手が不要な呼び出し向け)。
 */
export function validateBlockId(
  candidate: string,
  siblingIds: ReadonlySet<string>,
  currentId?: string,
): BlockIdError | null {
  return validateBlockIdDetailed(candidate, siblingIds, currentId)?.code ?? null;
}

/** Python keyword との一致 (valid だが warning を出す、ADR-0071 §(4))。 */
export function isReservedWord(candidate: string): boolean {
  return PYTHON_KEYWORDS.has(candidate);
}

function fallbackForType(type: string): unknown {
  // 文字列 type label の shallow 一致 (ADR-0019 §Open Question 4)。
  // container を先に check (= "list[int]" が "int" にマッチする誤りを避ける)。
  if (type.includes("list") || type.includes("ndarray") || type.includes("tuple")) {
    return [];
  }
  if (type.includes("dict")) return {};
  if (type.includes("bool")) return false;
  if (type.includes("int")) return 0;
  if (type.includes("float")) return 0;
  if (type.includes("str")) return "";
  return null;
}
