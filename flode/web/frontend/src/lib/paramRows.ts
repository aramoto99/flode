// ADR-0086 §5-B / §6-B: ユーザーブロックの行リスト引数の行エディタの純関数。
//
// - 行の操作 (追加・置き換え・削除・入れ替え) と、旧 → 新の行番号の対応表 (IndexRemap)
// - 対応表を配線 (connections) と手動分岐点 (branch_waypoints のキー) に当てる
// - 「テキストで編集…」の解析 (1 行 1 項目、前後の空白を削り空行を捨てる)
// - 表示の対応: describe の要求の行リストが今の行と同一なら位置で、違えば行の文字列で説明を当てる
//
// 配線は操作が作った対応表でだけ付け替える (旧・新の行リストを diff で突き合わせない)。

import type {
  BranchWaypointDict,
  ConnectionEntry,
  ParamRowsDescribeResponse,
  ParamRowsFieldValue,
  ParamRowsPorts,
  ParamRowsVariant,
  ParamSearchCell,
} from "../types/api";

/**
 * 行番号の対応表。``map.length`` = 操作前の行数、``map[i]`` = 行 i の新しい番号
 * (``null`` = その行は削除された)。``side`` はその引数の行が対応するポートの側。
 */
export interface IndexRemap {
  side: "input" | "output";
  map: ReadonlyArray<number | null>;
}

/** 行の操作の結果 (新しい行リスト・対応表・操作後に選ぶ行)。 */
export interface RowEdit {
  rows: string[];
  /** 旧 → 新の対応 (``IndexRemap.map`` と同じ意味)。 */
  map: ReadonlyArray<number | null>;
  /** 操作後に選択する行 (SPEC-0037 D6)。行が無くなれば ``null``。 */
  selected: number | null;
}

/**
 * 恒等の対応 (末尾追加: 既存の行の番号は変わらない)。
 *
 * @param n - 操作前の行数。
 */
export function remapAppend(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

/**
 * 恒等の対応 (置き換え: その行の配線はそのまま)。
 *
 * @param n - 操作前の行数。
 */
export function remapReplace(n: number): number[] {
  return remapAppend(n);
}

/**
 * 行 ``index`` を削除したときの対応 (後ろの行は 1 つ前へ詰まる)。
 *
 * @param n - 操作前の行数。
 * @param index - 削除する行。
 */
export function remapDelete(n: number, index: number): Array<number | null> {
  return Array.from({ length: n }, (_, i) => (i === index ? null : i < index ? i : i - 1));
}

/**
 * 行 ``i`` と ``j`` を入れ替えたときの対応。
 *
 * @param n - 操作前の行数。
 * @param i - 入れ替える行。
 * @param j - 入れ替える行。
 */
export function remapSwap(n: number, i: number, j: number): number[] {
  return Array.from({ length: n }, (_, k) => (k === i ? j : k === j ? i : k));
}

/**
 * 末尾に 1 行足す。
 *
 * @param rows - 今の行。
 * @param row - 足す行。
 */
export function appendRow(rows: ReadonlyArray<string>, row: string): RowEdit {
  return { rows: [...rows, row], map: remapAppend(rows.length), selected: rows.length };
}

/**
 * 行 ``index`` を置き換える。
 *
 * @param rows - 今の行。
 * @param index - 置き換える行 (範囲内)。
 * @param row - 新しい行。
 * @throws RangeError ``index`` が範囲外。
 */
export function replaceRow(rows: ReadonlyArray<string>, index: number, row: string): RowEdit {
  assertIndex(rows, index);
  const next = [...rows];
  next[index] = row;
  return { rows: next, map: remapReplace(rows.length), selected: index };
}

/**
 * 行 ``index`` を削除する。削除後は同じ位置 (末尾なら 1 つ上) を選ぶ。
 *
 * @param rows - 今の行。
 * @param index - 削除する行 (範囲内)。
 * @throws RangeError ``index`` が範囲外。
 */
export function deleteRow(rows: ReadonlyArray<string>, index: number): RowEdit {
  assertIndex(rows, index);
  const next = rows.filter((_, i) => i !== index);
  const selected = next.length === 0 ? null : Math.min(index, next.length - 1);
  return { rows: next, map: remapDelete(rows.length, index), selected };
}

/**
 * 行 ``i`` と ``j`` を入れ替える (↑ / ↓)。入れ替え後は動かした行 (``j``) を選ぶ。
 *
 * @param rows - 今の行。
 * @param i - 動かす行 (範囲内)。
 * @param j - 行き先 (範囲内)。
 * @throws RangeError ``i`` / ``j`` が範囲外。
 */
export function swapRows(rows: ReadonlyArray<string>, i: number, j: number): RowEdit {
  assertIndex(rows, i);
  assertIndex(rows, j);
  const next = [...rows];
  next[i] = rows[j]!;
  next[j] = rows[i]!;
  return { rows: next, map: remapSwap(rows.length, i, j), selected: j };
}

function assertIndex(rows: ReadonlyArray<string>, index: number): void {
  if (!Number.isInteger(index) || index < 0 || index >= rows.length) {
    throw new RangeError(`row index out of range: ${index} (rows: ${rows.length})`);
  }
}

/**
 * 操作の対応を、describe の ``ports`` に応じた ``IndexRemap`` の列にする。
 * ``ports`` が ``null`` (ポートに対応しない引数・describe の失敗中) なら空 = 番号で対応。
 *
 * @param map - 操作が作った旧 → 新の対応。
 * @param ports - 表示中の describe の ``ports``。
 */
export function toRemaps(
  map: ReadonlyArray<number | null>,
  ports: ParamRowsPorts,
): IndexRemap[] {
  return ports === null ? [] : [{ side: ports, map }];
}

/**
 * 対応表を配線に当てる。入力側は ``dst === blockId`` の ``dst_idx``、出力側は
 * ``src === blockId`` の ``src_idx`` を書き換え、削除行の配線は落とす。
 * ``idx >= map.length`` (行に対応しないポート) の配線は触らない (後段の剪定に任せる)。
 *
 * @param connections - そのスコープの配線。
 * @param blockId - 行エディタのブロック。
 * @param remap - 対応表。
 * @returns 新しい配線 (変化が無ければ同じ配列)。
 */
export function remapConnections(
  connections: ConnectionEntry[],
  blockId: string,
  remap: IndexRemap,
): ConnectionEntry[] {
  let changed = false;
  const out: ConnectionEntry[] = [];
  for (const c of connections) {
    const own = remap.side === "input" ? c.dst === blockId : c.src === blockId;
    const idx = remap.side === "input" ? c.dst_idx : c.src_idx;
    if (!own || idx < 0 || idx >= remap.map.length) {
      out.push(c);
      continue;
    }
    const next = remap.map[idx];
    if (next === null || next === undefined) {
      changed = true; // 削除行の配線は消す
      continue;
    }
    if (next === idx) {
      out.push(c);
      continue;
    }
    changed = true;
    out.push(remap.side === "input" ? { ...c, dst_idx: next } : { ...c, src_idx: next });
  }
  return changed ? out : connections;
}

/**
 * 対応表を手動分岐点のキー ``"<blockId>:<idx>"`` に当てる (出力側だけ。入力側は何もしない)。
 * 削除行のキーは落とす。付け替えないと分岐点の固定位置が別の出力へ移る (ADR-0057)。
 *
 * @param waypoints - そのスコープの branch_waypoints。
 * @param blockId - 行エディタのブロック。
 * @param remap - 対応表。
 * @returns 新しい dict (変化が無ければ同じ参照)。
 */
export function remapBranchWaypoints(
  waypoints: BranchWaypointDict,
  blockId: string,
  remap: IndexRemap,
): BranchWaypointDict {
  return remapPortKeyedDict(waypoints, blockId, remap);
}

/**
 * 対応表を出力ポート単位の合成キー ``"<blockId>:<idx>"`` を持つ dict に当てる
 * (手動分岐点 ADR-0057・信号名 ADR-0087 で共用。出力側だけ。入力側は何もしない)。
 * 削除行のキーは落とす。値には触らない。
 *
 * @param dict - そのスコープの ``"<id>:<idx>"`` キーの dict。
 * @param blockId - 番号が変わるブロック。
 * @param remap - 対応表。
 * @returns 新しい dict (変化が無ければ同じ参照)。
 */
export function remapPortKeyedDict<T>(
  dict: Record<string, T>,
  blockId: string,
  remap: IndexRemap,
): Record<string, T> {
  const waypoints = dict;
  if (remap.side !== "output") return waypoints;
  const prefix = `${blockId}:`;
  let changed = false;
  const out: Record<string, T> = {};
  // 先に他のキーを写し、付け替えたキーで上書きされないようにする (番号は全単射なので重ならない)
  const moved: Array<[string, T]> = [];
  for (const [key, value] of Object.entries(waypoints)) {
    const idx = key.startsWith(prefix) ? parsePortIndex(key.slice(prefix.length)) : null;
    if (idx === null || idx >= remap.map.length) {
      out[key] = value;
      continue;
    }
    const next = remap.map[idx];
    if (next === null || next === undefined) {
      changed = true;
      continue;
    }
    if (next !== idx) changed = true;
    moved.push([`${prefix}${next}`, value]);
  }
  if (!changed) return waypoints;
  for (const [key, value] of moved) out[key] = value;
  return out;
}

/** ``"12"`` → 12。非負整数の 10 進表記でなければ ``null``。 */
function parsePortIndex(text: string): number | null {
  return /^(0|[1-9][0-9]*)$/.test(text) ? Number(text) : null;
}

/**
 * 「テキストで編集…」の内容を行のリストにする (SPEC-0037 D7: 前後の空白を削り、空行を捨てる)。
 *
 * @param text - textarea の内容。
 */
export function parseTextList(text: string): string[] {
  return text
    .split(/\r\n|\r|\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/**
 * 行のリストを「テキストで編集…」の初期内容 (改行区切り) にする。
 *
 * @param rows - 今の行。
 */
export function formatTextList(rows: ReadonlyArray<string>): string {
  return rows.join("\n");
}

/** describe の結果と、その要求に使った行リスト。 */
export interface DescribedRows {
  requestRows: ReadonlyArray<string>;
  result: ParamRowsDescribeResponse;
}

/** 表に描く 1 行。 */
export interface DisplayRow {
  cells: ReadonlyArray<ParamSearchCell>;
  error: string | null;
  /** 説明待ち (今の行に対応する説明がまだ無い)。生の文字列を 1 列目に薄く出す。 */
  dim: boolean;
}

/**
 * 今の行に describe の説明を当てる (ADR-0086 §6-B / データ整合性の観点 2)。
 *
 * - ``described`` が無い (取得前・失敗中) → ``columns: null`` (呼ぶ側が生の文字列 1 列で描く)
 * - 要求の行リストが今の行と同一 → 位置で対応
 * - 違う (操作直後で describe 待ち) → 行の文字列で引き、引けない行は生の文字列で ``dim``
 *   (番号で古い説明を当てない。削除直後に後ろの行へずれた説明が出るのを防ぐ)
 *
 * @param rows - 今の行。
 * @param described - 最新の describe の結果 (無ければ ``null``)。
 */
export function displayRows(
  rows: ReadonlyArray<string>,
  described: DescribedRows | null,
): { columns: string[] | null; rows: DisplayRow[] } {
  if (described === null) {
    return { columns: null, rows: rows.map((r) => ({ cells: [r], error: null, dim: false })) };
  }
  const { requestRows, result } = described;
  const width = Math.max(1, result.columns.length);
  const same =
    requestRows.length === rows.length && requestRows.every((r, i) => r === rows[i]);
  if (same && result.rows.length === rows.length) {
    return {
      columns: result.columns,
      rows: result.rows.map((d) => ({ cells: d.cells, error: d.error, dim: false })),
    };
  }
  // 前提: describe は行ごとに独立 (同じ文字列の行には同じ説明が返る) ので、文字列で引いてよい
  const byText = new Map<string, ParamRowsDescribeResponse["rows"][number]>();
  requestRows.forEach((r, i) => {
    const d = result.rows[i];
    if (d !== undefined && !byText.has(r)) byText.set(r, d);
  });
  return {
    columns: result.columns,
    rows: rows.map((r) => {
      const d = byText.get(r);
      if (d !== undefined) return { cells: d.cells, error: d.error, dim: false };
      const cells: ParamSearchCell[] = [r, ...Array.from({ length: width - 1 }, () => null)];
      return { cells, error: null, dim: true };
    }),
  };
}

/** pick フィールドで選べる値の上限 (サーバの ``MAX_PARAM_ROWS_PICK_VALUES`` と同じ)。 */
export const MAX_PICK_VALUES = 128;

/**
 * 種類のフィールドの値を、与えられた値と既定値で埋める (ADR-0086 §2-C)。
 * 既定: text は ``""``、choice は先頭の選択肢、pick は ``[]``。型の合わない値・choice の
 * 選択肢に無い値・他の種類のキーは使わない (種類を切り替えたときはすべて既定になる)。
 *
 * @param variant - 選ばれた種類。
 * @param given - form の応答の ``values`` (無ければ ``{}``)。
 */
export function fieldValuesFor(
  variant: ParamRowsVariant,
  given: Readonly<Record<string, ParamRowsFieldValue>> = {},
): Record<string, ParamRowsFieldValue> {
  const out: Record<string, ParamRowsFieldValue> = {};
  for (const field of variant.fields) {
    const raw = Object.prototype.hasOwnProperty.call(given, field.key) ? given[field.key] : undefined;
    if (field.kind === "pick") {
      out[field.key] = Array.isArray(raw)
        ? raw.filter((x): x is string => typeof x === "string").slice(0, MAX_PICK_VALUES)
        : [];
    } else if (field.kind === "choice") {
      const options = field.options ?? [];
      out[field.key] =
        typeof raw === "string" && options.some((o) => o.value === raw)
          ? raw
          : (options[0]?.value ?? "");
    } else {
      out[field.key] = typeof raw === "string" ? raw : "";
    }
  }
  return out;
}

/** 行・他の引数・フィールドの値が変わってから describe / compose を送るまでの待ち (ms)。 */
export const PARAM_ROWS_DEBOUNCE_MS = 300;

/**
 * セル・列見出しの表示上限 (文字数)。サーバ (ADR-0086 §2-B) も 200 字で切って返すので同じ値にする
 * (二重に短くしない。サーバ側の値を変えたらここも揃える)。
 */
export const PARAM_ROWS_CELL_CHARS = 200;
