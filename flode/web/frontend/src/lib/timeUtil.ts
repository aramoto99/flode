// 時刻関連ユーティリティ (ADR-0042 §論点 3-A / §論点 5-A)。
//
// backend は ``Stop Time = ∞`` (unbounded) を ``"inf"`` 文字列リテラルで
// wire 配信する (= JS ``JSON.stringify(Infinity)==="null"`` の罠回避)。
// frontend 内では ``Number.POSITIVE_INFINITY`` に正規化してから比率計算等で
// 扱う。本ヘルパーは Toolbar 入力 / WS progress / REST state の 3 箇所で
// 共通利用する。

import type { TEnd } from "../types/api";

export interface ParsedTEnd {
  /** ``Number.POSITIVE_INFINITY`` (unbounded) または有限正値 */
  value: number;
  /** ``true`` のとき unbounded (= UI で progress bar 非表示等に使う) */
  isUnbounded: boolean;
}

/**
 * wire / store から取り出した ``t_end`` を計算可能な数値に正規化する。
 *
 * @param raw ``number | "inf"`` の Union 値。``"INF"`` 等 case 違いも受容。
 * @returns ``{value, isUnbounded}``。``isUnbounded === true`` で
 *   ``value === Number.POSITIVE_INFINITY``。
 *
 * @remarks
 * Toolbar 入力 (= 利用者が typing する文字列) は別関数 ``parseToolbarTEnd``
 * を使う (= 数値リテラル + ``"inf"`` の双方を扱う)。本関数は backend からの
 * 配信値を扱うため number か ``"inf"`` 限定で良い。
 */
export function parseTEnd(raw: TEnd): ParsedTEnd {
  if (typeof raw === "number") {
    if (Number.isFinite(raw)) {
      return { value: raw, isUnbounded: false };
    }
    // 通常 backend は number 型で Infinity を出さない (= "inf" 文字列で出す)。
    // 防御的に Infinity も unbounded として扱う。
    return { value: Number.POSITIVE_INFINITY, isUnbounded: true };
  }
  // string ("inf"、case-insensitive); 万が一の typo で他の string が来た場合は
  // unbounded fallback (= safer than crashing the UI)。
  return { value: Number.POSITIVE_INFINITY, isUnbounded: true };
}

/**
 * Toolbar の Stop Time フィールドの入力値を ``TEnd`` (wire 形式) に変換する。
 *
 * ADR-0042 §論点 5-A: ``"inf"`` (case-insensitive、前後空白許容) は受け入れる。
 * ``"+inf"`` / ``"infinity"`` / ``"∞"`` 等は **拒否** (= backend の ``parse_t_end``
 * と完全一致)。空文字や不正値は ``null`` を返し、呼び出し側で「入力受け付けず」
 * 表示する。正の有限数は ``number``、``"inf"`` (case-insensitive) は文字列
 * リテラル ``"inf"`` を返す。
 */
export function parseToolbarTEnd(input: string): TEnd | null {
  const trimmed = input.trim();
  if (trimmed.length === 0) return null;
  if (trimmed.toLowerCase() === "inf") return "inf";
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return null;
  if (n <= 0) return null;
  return n;
}
