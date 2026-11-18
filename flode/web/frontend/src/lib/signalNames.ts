// ADR-0087 / SPEC-0038: 信号名 (出力ポート単位の名前) の純関数。
//
// - 名前の規則 (D6): 前後の空白を除き NFC にそろえる、改行・制御文字・孤立サロゲートは不可、
//   64 コードポイントまで (backend ``flode.core.persistence.is_valid_signal_name`` と同じ規則)
// - 検証付きの読み出し (キーの形・値の規則。不正なものは表示しない)
// - 追従の「消す側」の一元化 (``reconcileSignalNames``): 出力ポートの配線が 1 本も無いキーを消す
// - id の付け替え (``renamePortKeyedDictId``、手動分岐点と共用)

import type { BlockEntry, ConnectionEntry, FlwModel, SignalNameDict } from "../types/api";

/** 信号名の最大長 (NFC 後のコードポイント数)。backend の ``MAX_SIGNAL_NAME_CHARS`` と同じ。 */
export const MAX_SIGNAL_NAME_CHARS = 64;

/** 信号名の検証エラーの種類 (i18n キー ``signal_name.error_<kind>`` に対応)。 */
export type SignalNameError = "too_long" | "control_char";

// 改行・制御文字 (Cc)・行区切り (Zl)・段落区切り (Zp)・孤立サロゲート (Cs)
const FORBIDDEN_CHARS_RE = /[\p{Cc}\p{Zl}\p{Zp}\p{Cs}]/u;
// "<src_id>:<src_idx>" (最後の ":" で分ける。id に ":" は使えない、ADR-0071)
const PORT_KEY_RE = /^([\s\S]+):(0|[1-9][0-9]*)$/;

/**
 * 入力された名前を保存する形にそろえる (前後の空白を除き NFC)。
 *
 * @param raw - 入力欄の文字列。
 * @returns 正規化した名前 (空文字 = 名前なし)。
 */
export function normalizeSignalName(raw: string): string {
  return raw.trim().normalize("NFC");
}

/**
 * 正規化済みの名前を検査する。空文字は「名前を消す」なので正しいとみなす。
 *
 * @param normalized - ``normalizeSignalName`` の結果。
 * @returns 規則違反の種類 (問題が無ければ ``null``)。
 */
export function validateSignalName(normalized: string): SignalNameError | null {
  if (FORBIDDEN_CHARS_RE.test(normalized)) return "control_char";
  if ([...normalized].length > MAX_SIGNAL_NAME_CHARS) return "too_long";
  return null;
}

/** 保存されている値が名前として正しいか (文字列・空でない・規則どおり)。 */
function isStoredNameValid(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const normalized = normalizeSignalName(value);
  return normalized !== "" && validateSignalName(normalized) === null;
}

/**
 * 合成キー ``"<src_id>:<src_idx>"`` を分解する。
 *
 * @param key - キー。
 * @returns 接続元 id と出力番号 (形が違えば ``null``)。
 */
export function parsePortKey(key: string): { src: string; srcIdx: number } | null {
  const m = PORT_KEY_RE.exec(key);
  if (!m) return null;
  return { src: m[1]!, srcIdx: Number(m[2]) };
}

/** 出力ポートの合成キー。 */
export function portKey(src: string, srcIdx: number): string {
  return `${src}:${srcIdx}`;
}

/** own property として値を書く (``__proto__`` キーで prototype を汚さない)。 */
function defineOwn<T>(out: Record<string, T>, key: string, value: T): void {
  Object.defineProperty(out, key, { value, enumerable: true, writable: true, configurable: true });
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * スコープの ``signal_names`` を検証して読む。キーの形が違う・値が名前の規則に合わない
 * ものは除く (表示しない)。値は正規化した形で返す。
 *
 * @param raw - スコープの ``signal_names`` (任意の JSON 値)。
 * @returns キー → 名前の Map (無ければ空)。
 */
export function readSignalNames(raw: unknown): Map<string, string> {
  const out = new Map<string, string>();
  if (!isPlainRecord(raw)) return out;
  for (const [key, value] of Object.entries(raw)) {
    if (parsePortKey(key) === null || !isStoredNameValid(value)) continue;
    out.set(key, normalizeSignalName(value));
  }
  return out;
}

/**
 * 配線の一覧から「1 本以上配線がある出力ポート」のキー集合を作る。
 *
 * @param connections - スコープの配線 (配列でなければ空とみなす)。
 */
function connectedPortKeys(connections: unknown): Set<string> {
  const keys = new Set<string>();
  if (!Array.isArray(connections)) return keys;
  for (const c of connections as ConnectionEntry[]) {
    if (c && typeof c.src === "string" && typeof c.src_idx === "number") {
      keys.add(portKey(c.src, c.src_idx));
    }
  }
  return keys;
}

/**
 * 1 スコープの ``signal_names`` から、配線が無い・形が不正なキーを除く。
 *
 * @returns 新しい dict (変化が無ければ ``names`` そのもの、全部消えたら ``undefined``)。
 */
function pruneScopeSignalNames(
  connections: unknown,
  names: unknown,
): SignalNameDict | undefined {
  if (!isPlainRecord(names)) return undefined;
  const connected = connectedPortKeys(connections);
  const out: SignalNameDict = {};
  let changed = false;
  let count = 0;
  for (const [key, value] of Object.entries(names)) {
    if (parsePortKey(key) === null || !isStoredNameValid(value) || !connected.has(key)) {
      changed = true;
      continue;
    }
    defineOwn(out, key, value);
    count += 1;
  }
  if (count === 0) return undefined;
  return changed ? out : (names as SignalNameDict);
}

function isSubsystemEntry(b: unknown): b is BlockEntry & { params: Record<string, unknown> } {
  if (!isPlainRecord(b)) return false;
  const params = b.params;
  return isPlainRecord(params) && Array.isArray(params.blocks);
}

/** スコープ (最上位のモデル or Subsystem の params) を 1 つ reconcile する。 */
function reconcileScope<S extends Record<string, unknown>>(prev: S | undefined, next: S): S {
  let out = next;
  // (1) このスコープの名前。接続・名前のどちらも前と同じ参照なら見ない (構造共有)
  if (
    "signal_names" in next &&
    !(prev !== undefined && prev.signal_names === next.signal_names &&
      prev.connections === next.connections)
  ) {
    const pruned = pruneScopeSignalNames(next.connections, next.signal_names);
    if (pruned !== next.signal_names) {
      const copy: Record<string, unknown> = { ...next };
      if (pruned === undefined) delete copy.signal_names;
      else copy.signal_names = pruned;
      out = copy as S;
    }
  }
  // (2) 入れ子の Subsystem。前と同じ参照のブロックの中は見ない
  const blocks = next.blocks;
  if (!Array.isArray(blocks)) return out;
  const prevBlocks = prev !== undefined && Array.isArray(prev.blocks) ? prev.blocks : null;
  if (prevBlocks === blocks) return out;
  let prevById: Map<string, unknown> | null = null;
  if (prevBlocks !== null) {
    prevById = new Map();
    for (const pb of prevBlocks as unknown[]) {
      if (isPlainRecord(pb) && typeof pb.id === "string") prevById.set(pb.id, pb);
    }
  }
  let newBlocks: unknown[] | null = null;
  (blocks as unknown[]).forEach((b, i) => {
    if (!isSubsystemEntry(b)) return;
    const pb = prevById?.get(b.id);
    if (pb === b) return;
    const prevParams = isSubsystemEntry(pb) ? pb.params : undefined;
    const params = reconcileScope(prevParams, b.params);
    if (params === b.params) return;
    newBlocks ??= [...(blocks as unknown[])];
    newBlocks[i] = { ...b, params };
  });
  if (newBlocks !== null) out = { ...out, blocks: newBlocks } as S;
  return out;
}

/**
 * 追従の「消す側」を 1 か所で行う (ADR-0087 論点 4 T3)。各スコープの ``signal_names`` から、
 * そのスコープの配線に ``src``・``src_idx`` が一致するものが 1 本も無いキー (接続元の削除・
 * 出力ポート数の減少・配線の全削除) と、形・値が不正なキーを消す。空になったらキーごと消す。
 *
 * ``prev`` と同じ参照のスコープ・ブロックは見ない (編集したスコープだけを見る)。
 * 変化が無ければ ``next`` をそのまま返す。
 *
 * @param prev - 編集前のモデル (全スコープを見るときは ``null``)。
 * @param next - 編集後のモデル。
 * @returns 掃除したモデル。
 */
export function reconcileSignalNames(prev: FlwModel | null, next: FlwModel): FlwModel {
  if (prev === next) return next;
  const out = reconcileScope(
    prev === null ? undefined : (prev as unknown as Record<string, unknown>),
    next as unknown as Record<string, unknown>,
  );
  return out as unknown as FlwModel;
}

/**
 * ``"<id>:<idx>"`` キーの dict で、id 部が ``oldId`` のキーを ``newId`` に付け替える
 * (ブロック名の変更。手動分岐点と信号名で共用)。キーの順序は保つ。
 *
 * @param dict - スコープの dict。
 * @param oldId - 変更前の id。
 * @param newId - 変更後の id。
 * @returns 新しい dict (変化が無ければ同じ参照)。
 */
export function renamePortKeyedDictId<T>(
  dict: Record<string, T>,
  oldId: string,
  newId: string,
): Record<string, T> {
  let changed = false;
  const out: Record<string, T> = {};
  for (const [key, value] of Object.entries(dict)) {
    const sep = key.lastIndexOf(":");
    if (sep >= 0 && key.slice(0, sep) === oldId) {
      defineOwn(out, `${newId}${key.slice(sep)}`, value);
      changed = true;
    } else {
      defineOwn(out, key, value);
    }
  }
  return changed ? out : dict;
}

/**
 * ``"<id>:<idx>"`` キーの dict を、id を付け替えて別の dict に写す (貼り付け)。
 * ``idMap`` に無い id のキーは写さない。
 *
 * @param dict - コピー元の dict。
 * @param idMap - 旧 id → 新 id。
 */
export function remapPortKeyedDictIds<T>(
  dict: Readonly<Record<string, T>>,
  idMap: ReadonlyMap<string, string>,
): Record<string, T> {
  const out: Record<string, T> = {};
  for (const [key, value] of Object.entries(dict)) {
    const parsed = parsePortKey(key);
    const newId = parsed ? idMap.get(parsed.src) : undefined;
    if (parsed && newId !== undefined) defineOwn(out, portKey(newId, parsed.srcIdx), value);
  }
  return out;
}
