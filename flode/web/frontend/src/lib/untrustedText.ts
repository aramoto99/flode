// ADR-0081: サーバ由来の文字列 (ユーザーブロックの表示名・説明・カテゴリ・パラメータ説明・
// 選択肢・ファイル名・読み込みエラーのメッセージ・構造化エラーの引数) を画面に出す前の整形。
//
// これらはユーザーの .py (= 第三者から受け取ったファイルかもしれない) に由来するため、
// 信頼できない文字列として扱う。React のテキストノード / ``title`` 属性としてのみ描画し
// (HTML としては解釈させない)、ここでは見た目を壊す・偽装する文字だけを取り除く:
//   - 制御文字 (C0 / DEL / C1)。改行・タブは空白 1 個にする
//   - 双方向制御文字 (表示順を入れ替えて別の文字列に見せる攻撃に使われる)
//   - 長すぎる文字列は末尾を省略記号で切る

/** 表示名・ラベル・選択肢など 1 行の短い文字列の上限 (文字数)。 */
export const MAX_LABEL_CHARS = 80;
/** 型名・ファイルパスの上限。 */
export const MAX_PATH_CHARS = 200;
/** 説明文 (ブロック・パラメータ) の上限。 */
export const MAX_DESCRIPTION_CHARS = 300;
/** 読み込みエラー・サーバの理由文の上限。 */
export const MAX_MESSAGE_CHARS = 500;

const ELLIPSIS = "…";

// 改行・タブ → 空白 (1 行の表示に揃える)
const LINE_BREAKS = /[\t\n\r\u2028\u2029]+/g;
// C0 制御文字 (改行・タブは上で置換済み)・DEL・C1 制御文字
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f]/g;
// 双方向制御文字: LRM / RLM / ALM、LRE〜RLO (埋め込み・上書き)、LRI〜PDI (分離)
const BIDI_CONTROLS = /[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]/g;

/**
 * サーバ由来の信頼できない文字列を、画面に 1 行で出せる形に整える。
 *
 * 文字列以外 (``null`` / 数値 / オブジェクト) は空文字にする (JSON の形が想定と違っても
 * 例外にしない)。長さはサロゲートペアを分断しないよう code point 単位で数える。
 *
 * @param value - サーバから受け取った値。
 * @param maxChars - 上限文字数 (超えたら ``…`` で終わる ``maxChars`` 文字にする)。
 * @returns 整形済みの文字列。
 */
export function cleanServerText(value: unknown, maxChars: number): string {
  if (typeof value !== "string") return "";
  const cleaned = value
    .replace(LINE_BREAKS, " ")
    .replace(CONTROL_CHARS, "")
    .replace(BIDI_CONTROLS, "")
    .trim();
  const chars = Array.from(cleaned);
  if (chars.length <= maxChars) return cleaned;
  return chars.slice(0, Math.max(0, maxChars - 1)).join("") + ELLIPSIS;
}
