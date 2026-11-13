// ADR-0080 §新しいエラーコード: ライブラリ API のエラーを表示文言に変換する。
//
// サーバは ``{category: "library", template_key: "error.library.<code>",
// template_args: {message, ...}}`` を返す。コード・引数の形が変わったときに
// 直す場所を 1 箇所にするため、コード → i18n キーの対応と引数の整形は本ファイルに
// 集約する (UI 側は ``describeLibraryError`` / ``libraryErrorCode`` だけを使う)。

import type { TFunction } from "i18next";

import { ApiError } from "../api/client";
import type en from "../i18n/locales/en.json";
import type { UserLibraryStatus } from "../types/api";

/** 翻訳キー (en.json 由来)。下の対応表のキーが実在することを型で検査する。 */
type TranslationKey = keyof typeof en;

/**
 * 動的に選んだキーで翻訳する。対応表は ``satisfies`` でキーの実在を検査済みなので、
 * ここでは i18next の (リテラルキーごとの) 補間引数の型検査だけを外す。
 */
function tr(t: TFunction, key: TranslationKey, args?: Record<string, unknown>): string {
  return (t as (key: string, args?: Record<string, unknown>) => string)(key, args);
}

const LIBRARY_ERROR_CATEGORY = "library";
const LIBRARY_TEMPLATE_PREFIX = "error.library.";

/** サーバのエラーコード → i18n キー (キーの存在は en.json 由来の型で検査される)。 */
const ERROR_KEYS = {
  library_write_forbidden: "error.library.library_write_forbidden",
  user_library_disabled: "error.library.user_library_disabled",
  library_path_unsafe: "error.library.library_path_unsafe",
  library_read_only: "error.library.library_read_only",
  library_not_found: "error.library.library_not_found",
  library_entry_not_found: "error.library.library_entry_not_found",
  library_entry_name_conflict: "error.library.library_entry_name_conflict",
  library_entry_conflict: "error.library.library_entry_conflict",
  library_changed_on_disk: "error.library.library_changed_on_disk",
  user_library_corrupt: "error.library.user_library_corrupt",
  library_schema_too_new: "error.library.library_schema_too_new",
  library_name_conflict: "error.library.library_name_conflict",
  library_entry_invalid: "error.library.library_entry_invalid",
  library_file_invalid: "error.library.library_file_invalid",
  library_write_busy: "error.library.library_write_busy",
  library_write_failed: "error.library.library_write_failed",
} as const satisfies Record<string, TranslationKey>;

/** frontend が文言を持つライブラリ API のエラーコード。 */
export type LibraryErrorCode = keyof typeof ERROR_KEYS;

/** ``library_entry_invalid`` の ``reason`` → 詳細文言のキー。 */
const ENTRY_INVALID_KEYS = {
  invalid_metadata: "error.library.entry_invalid.invalid_metadata",
  invalid_block: "error.library.entry_invalid.invalid_block",
  unknown_types: "error.library.entry_invalid.unknown_types",
  goto_from_not_closed: "error.library.entry_invalid.goto_from_not_closed",
} as const satisfies Record<string, TranslationKey>;

/** Goto/From 閉包違反 1 件の ``reason`` → 文言のキー。 */
const VIOLATION_KEYS = {
  global_goto: "error.library.violation.global_goto",
  unresolved_from: "error.library.violation.unresolved_from",
  duplicate_goto: "error.library.violation.duplicate_goto",
} as const satisfies Record<string, TranslationKey>;

/** ``library_file_invalid`` の ``reason`` → 詳細文言のキー。 */
const FILE_INVALID_KEYS = {
  invalid_json: "error.library.file_invalid.invalid_json",
  too_deep: "error.library.file_invalid.too_deep",
  invalid_library: "error.library.file_invalid.invalid_library",
  invalid_name: "error.library.file_invalid.invalid_name",
  invalid_metadata: "error.library.file_invalid.invalid_metadata",
  reserved_entry_id: "error.library.file_invalid.reserved_entry_id",
} as const satisfies Record<string, TranslationKey>;

/** ``library_name_conflict`` の ``reason`` → 文言のキー (未知の reason は exists 扱い)。 */
const NAME_CONFLICT_KEYS = {
  reserved: "error.library.name_conflict.reserved",
  exists: "error.library.name_conflict.exists",
  uid_exists: "error.library.name_conflict.uid_exists",
} as const satisfies Record<string, TranslationKey>;

/** 文言の補間に使う ``template_args`` の名前 (文字列・数値のもの)。 */
const KNOWN_ARG_NAMES = [
  "message",
  "file",
  "library",
  "origin",
  "entry_id",
  "display_name",
  "expected_revision",
  "current_revision",
  "path",
  "reason",
  "schema_version",
  "field",
  "max_chars",
] as const;

/** 構造化エラーでない HTTP status (本文サイズの検査) → 文言のキー。 */
const HTTP_STATUS_KEYS = {
  "413": "error.library.request_too_large",
  "411": "error.library.length_required",
} as const satisfies Record<string, TranslationKey>;

/** ``obj`` 自身が ``key`` を持つか (``in`` と違い prototype 上の名前に一致しない)。 */
function hasKey<T extends object>(obj: T, key: string): key is keyof T & string {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

/**
 * ライブラリ API の構造化エラーならそのコードと引数を返す。それ以外は ``null``。
 * コードは ``template_key`` の接尾辞から取る (``error.library.<code>``)。
 */
function libraryErrorParts(
  err: unknown,
): { code: string; args: Record<string, unknown> } | null {
  if (!(err instanceof ApiError) || err.structured === null) return null;
  const { category, template_key: key, template_args: args } = err.structured;
  if (category !== LIBRARY_ERROR_CATEGORY || !key.startsWith(LIBRARY_TEMPLATE_PREFIX)) {
    return null;
  }
  return {
    code: key.slice(LIBRARY_TEMPLATE_PREFIX.length),
    args: typeof args === "object" && args !== null ? args : {},
  };
}

/** ライブラリ API のエラーコードを返す (ライブラリ API の構造化エラーでなければ ``null``)。 */
export function libraryErrorCode(err: unknown): string | null {
  return libraryErrorParts(err)?.code ?? null;
}

/** ライブラリ API のエラーの ``template_args`` を返す (該当しなければ空 object)。 */
export function libraryErrorArgs(err: unknown): Record<string, unknown> {
  return libraryErrorParts(err)?.args ?? {};
}

/** 文言に差し込むサーバ由来の文字列 1 つの最大長 (code unit)。超過分は「…」で切る。 */
const MAX_ARG_CHARS = 300;

/**
 * サーバ由来の値を表示用の文字列にする。``template_args`` の中身 (ライブラリ名・パス・
 * 型名・raw message など) は信頼できない文字列なので、長さを切り、改行と制御文字・
 * 双方向制御文字を空白に畳む (レイアウト崩れ・表示の偽装を防ぐ)。描画は常にテキスト
 * ノードで行う (HTML としては解釈させない)。
 */
function asString(value: unknown): string {
  return sanitizeDisplayText(value, MAX_ARG_CHARS);
}

/**
 * 信頼できない値 (サーバの応答・取り込むファイル・モデルファイル由来) を表示用の
 * 文字列にする: 制御文字・書式文字 (双方向制御を含む)・行区切りを空白に畳み、
 * ``maxChars`` を超える分は「…」で切る。描画は常にテキストノードで行うこと。
 *
 * @param value 表示したい値 (``null`` / ``undefined`` は空文字)。
 * @param maxChars 最大長 (code unit)。
 */
export function sanitizeDisplayText(value: unknown, maxChars: number): string {
  if (value === undefined || value === null) return "";
  const text = (typeof value === "string" ? value : String(value))
    .replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]+/gu, " ")
    .trim();
  return text.length > maxChars ? `${text.slice(0, maxChars)}…` : text;
}

/** ``goto_from_not_closed`` の違反一覧を「パス (tag): 理由」の列に整形する。 */
function formatViolations(t: TFunction, raw: unknown): string {
  if (!Array.isArray(raw)) return "";
  return raw
    .map((v: unknown) => {
      const item = (typeof v === "object" && v !== null ? v : {}) as Record<string, unknown>;
      const reason = asString(item.reason);
      const args = { path: asString(item.path), tag: asString(item.tag) };
      return hasKey(VIOLATION_KEYS, reason)
        ? tr(t, VIOLATION_KEYS[reason], args)
        : tr(t, "error.library.violation.other", args);
    })
    .join("; ");
}

/** ``library_entry_invalid`` の理由別の詳細文言。 */
function entryInvalidDetail(t: TFunction, args: Record<string, unknown>): string {
  const reason = asString(args.reason);
  if (!hasKey(ENTRY_INVALID_KEYS, reason)) return asString(args.message);
  return tr(t, ENTRY_INVALID_KEYS[reason], {
    message: asString(args.message),
    field: asString(args.field),
    types: Array.isArray(args.unknown_types) ? args.unknown_types.map(asString).join(", ") : "",
    violations: formatViolations(t, args.violations),
  });
}

/**
 * ライブラリ API のエラーを、現在の言語の表示文言に変換する。
 *
 * ライブラリ API の構造化エラーでない場合 (ネットワーク断・413 など) は ``Error`` の
 * message をそのまま返す。未知のコードはサーバの英語 message に fallback する。
 *
 * @param t i18next の翻訳関数。
 * @param err ``catch`` した値。
 */
export function describeLibraryError(t: TFunction, err: unknown): string {
  const parts = libraryErrorParts(err);
  if (parts === null) {
    // 本文サイズの検査 (413 / 411) は FastAPI 標準の文字列 detail で返る
    if (err instanceof ApiError && hasKey(HTTP_STATUS_KEYS, String(err.status))) {
      return tr(t, HTTP_STATUS_KEYS[String(err.status) as keyof typeof HTTP_STATUS_KEYS]);
    }
    return err instanceof Error ? err.message : String(err);
  }
  const { code, args } = parts;
  if (!hasKey(ERROR_KEYS, code)) {
    return tr(t, "error.library.unknown", { message: asString(args.message) || code });
  }
  // interpolation に渡すのは文字列化できる値だけ (配列・object は下で個別に整形)
  // サーバが引数を省いても ``{{name}}`` がそのまま画面に出ないよう、空文字で埋めておく
  const flat: Record<string, string> = Object.fromEntries(
    KNOWN_ARG_NAMES.map((name) => [name, ""]),
  );
  for (const [k, v] of Object.entries(args)) {
    if (typeof v === "string" || typeof v === "number") flat[k] = asString(v);
  }
  if (code === "library_entry_invalid") {
    const body = tr(t, ERROR_KEYS[code], { ...flat, detail: entryInvalidDetail(t, args) });
    const entryId = asString(args.entry_id);
    return entryId ? tr(t, "error.library.entry_prefix", { entry_id: entryId, body }) : body;
  }
  if (code === "library_file_invalid") {
    const reason = asString(args.reason);
    const detail = hasKey(FILE_INVALID_KEYS, reason)
      ? tr(t, FILE_INVALID_KEYS[reason], flat)
      : asString(args.message);
    return tr(t, ERROR_KEYS[code], { ...flat, detail });
  }
  if (code === "library_name_conflict") {
    return describeNameConflict(
      t,
      asString(args.library),
      asString(args.reason),
      asString(args.conflicts_with),
    );
  }
  const body = tr(t, ERROR_KEYS[code], flat);
  if (code === "user_library_corrupt" && args.has_backup === true) {
    return `${body} ${tr(t, "error.library.user_library_corrupt_backup")}`;
  }
  return body;
}

/**
 * 取り込みライブラリの名前衝突の文言 (409 ``library_name_conflict`` と dry-run の
 * ``conflict`` の両方で使う)。
 */
export function describeNameConflict(
  t: TFunction,
  library: string,
  reason: string,
  conflictsWith?: string,
): string {
  return tr(t, hasKey(NAME_CONFLICT_KEYS, reason) ? NAME_CONFLICT_KEYS[reason] : NAME_CONFLICT_KEYS.exists, {
    library: asString(library),
    // ``uid_exists``: 衝突相手 (同じ uid で既に読み込まれているライブラリ) の名前。
    // サーバが返さない場合は取り込もうとしたライブラリの名前で代用する
    conflicts_with: asString(conflictsWith) || asString(library),
  });
}

/**
 * ``write_disabled_reason`` (エラーコード文字列) をツールチップ用の文言にする。
 * 空文字 (= 書き込める) なら ``undefined``。
 */
export function describeWriteDisabledReason(t: TFunction, reason: string): string | undefined {
  if (!reason) return undefined;
  return hasKey(WRITE_DISABLED_KEYS, reason)
    ? tr(t, WRITE_DISABLED_KEYS[reason])
    : tr(t, "error.library.unknown", { message: reason });
}

/** ``write_disabled_reason`` → 無効化理由 (パス等の引数を持たない短い文言) のキー。 */
const WRITE_DISABLED_KEYS = {
  library_write_forbidden: "library.write_disabled.library_write_forbidden",
  user_library_disabled: "library.write_disabled.user_library_disabled",
  user_library_corrupt: "library.write_disabled.user_library_corrupt",
  library_schema_too_new: "library.write_disabled.library_schema_too_new",
  library_read_only: "library.write_disabled.library_read_only",
} as const satisfies Record<string, TranslationKey>;

const REASON_WRITE_FORBIDDEN = "library_write_forbidden";
const REASON_USER_LIBRARY_DISABLED = "user_library_disabled";

/**
 * エントリの登録・編集・削除ができない理由コードを返す (できるなら空文字)。
 * ``status`` が無い (一覧が未取得) 間は、理由なしの「不可」ではなく可として扱い、
 * 最終判定はサーバに任せる。
 */
export function entryWriteDisabledReason(status: UserLibraryStatus | undefined): string {
  if (status === undefined || status.writable) return "";
  return status.write_disabled_reason || REASON_USER_LIBRARY_DISABLED;
}

/**
 * 取り込み・取り込みライブラリの削除ができない理由コードを返す (できるなら空文字)。
 * 取り込み先はユーザーライブラリのディレクトリ配下なので、サーバが書き込みを許可し、
 * かつユーザーライブラリが有効なら使える (``user.flwlib.json`` が壊れていても使える)。
 */
export function libraryImportDisabledReason(status: UserLibraryStatus | undefined): string {
  const reason = entryWriteDisabledReason(status);
  return reason === REASON_WRITE_FORBIDDEN || reason === REASON_USER_LIBRARY_DISABLED
    ? reason
    : "";
}

/**
 * 再読み込みができない理由コードを返す (できるなら空文字)。再読み込みはユーザー
 * ライブラリが無効でも・壊れていても使え (復旧手段でもある)、閉じるのはサーバが
 * 書き込み API を許可していない (非 loopback) ときだけ。
 */
export function libraryReloadDisabledReason(status: UserLibraryStatus | undefined): string {
  return entryWriteDisabledReason(status) === REASON_WRITE_FORBIDDEN
    ? REASON_WRITE_FORBIDDEN
    : "";
}
