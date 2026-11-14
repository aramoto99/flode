// 時刻関連ユーティリティ (ADR-0042 §論点 3-A / §論点 5-A)。
//
// backend は ``Stop Time = ∞`` (unbounded) を ``"inf"`` 文字列リテラルで
// wire 配信する (= JS ``JSON.stringify(Infinity)==="null"`` の罠回避)。
// frontend 内では ``Number.POSITIVE_INFINITY`` に正規化してから比率計算等で
// 扱う。本ヘルパーは Toolbar 入力 / WS progress / REST state の 3 箇所で
// 共通利用する。

import type { TEnd } from "../types/api";

/** 終了時刻なし (unbounded) を画面に出すときの記号 (Toolbar placeholder / StatusBar)。 */
export const UNBOUNDED_SYMBOL = "∞";

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
 * と完全一致)。**空欄 (空白のみ含む) は ``"inf"``** = 終了時刻なし
 * (2026-11-14 ユーザー要望: Stop ボタンを押すまで実行)。不正値は ``null`` を
 * 返し、呼び出し側で「入力受け付けず」表示する。正の有限数は ``number``、
 * ``"inf"`` / 空欄は文字列リテラル ``"inf"`` を返す。
 */
export function parseToolbarTEnd(input: string): TEnd | null {
  const trimmed = input.trim();
  if (trimmed.length === 0) return "inf";
  if (trimmed.toLowerCase() === "inf") return "inf";
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return null;
  if (n <= 0) return null;
  return n;
}

/**
 * ``t_end`` を Toolbar の Stop Time 入力欄に表示する文字列に変換する。
 *
 * ``parseToolbarTEnd`` の逆変換。unbounded (``"inf"``) は **空文字** で表示し、
 * 入力欄の placeholder (``∞``) を見せる (= 空欄 = 終了時刻なし の対応を
 * 見た目と操作で一致させる)。モデル未選択 (``undefined``) も空文字。
 *
 * @param tEnd store の ``simulator.t_end``。未選択時は ``undefined``。
 * @returns 入力欄に置く文字列。
 */
export function formatToolbarTEnd(tEnd: TEnd | undefined): string {
  if (tEnd === undefined) return "";
  if (parseTEnd(tEnd).isUnbounded) return "";
  return String(tEnd);
}

/**
 * ``t_end`` を読み取り専用の表示 (StatusBar 等) 用の文字列に変換する。
 *
 * unbounded は ``UNBOUNDED_SYMBOL`` (``∞``)、有限値はそのまま。
 *
 * @param tEnd store の ``simulator.t_end``。
 * @returns 表示文字列。
 */
export function formatTEndLabel(tEnd: TEnd): string {
  return parseTEnd(tEnd).isUnbounded ? UNBOUNDED_SYMBOL : String(tEnd);
}
