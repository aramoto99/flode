// ADR-0081 §論点 3 / §論点 4 (U5): ユーザーブロックとプレースホルダをモデル (JSON) の上で扱う
// 純粋関数。キャンバスの描画・保存・実行要求の組み立て・実行前チェックが同じ規則を使う。
//
// - プレースホルダ: registry を取得済みで、その型が registry に無いブロック。entry は一切
//   書き換えずに保持する (除去・剪定・既定値補完の対象外)。registry 取得前は判定しない。
// - 消えた引数: registry にある (= プレースホルダでない) ユーザーブロックの entry に残って
//   いるが、registry の引数一覧に無い引数。保存時と実行要求の組み立て時に同じ関数
//   (``pruneRemovedParams``) で除く。組み込みブロックには適用しない。
// - 超過ポート: ユーザーブロックの registry のポート数を超える index に繋がった配線。自動では
//   消さず、描画でエラー表示し、実行前チェックで止める。
//
// 型名・ブロック id はモデルファイル由来 (信頼できない文字列) なので、画面に出す側
// (``placeholderTypeLabel`` を含む) は ``cleanServerText`` で整形する。

import type {
  BlockEntry,
  BlockMetadata,
  ConnectionEntry,
  FailurePayload,
  FlwModel,
} from "../types/api";
import { cleanServerText, MAX_LABEL_CHARS, MAX_PATH_CHARS } from "./untrustedText";
import { isUserBlock } from "./userBlocks";

/** type_path → registry のメタデータ。 */
export type RegistryIndex = ReadonlyMap<string, BlockMetadata>;

/** 超過ポート (と、そこに繋がった配線) のエラー色 (rose-600、ui-design-system の Error 系)。 */
export const EXCESS_PORT_STROKE = "#e11d48";
/** プレースホルダの枠の色 (amber-700、ui-design-system の Warning)。 */
export const PLACEHOLDER_STROKE = "#b45309";
/** プレースホルダの型名ラベルの上限 (末尾を残して先頭を切る)。 */
export const PLACEHOLDER_TYPE_LABEL_CHARS = 28;
const ELLIPSIS = "…";
/** 実行前チェックの FailurePayload の category / template_key。 */
export const UNKNOWN_BLOCK_TYPE_CATEGORY = "unknown_block_type";
export const UNKNOWN_BLOCK_TYPE_TEMPLATE_KEY = "error.unknown_block_type";
export const EXCESS_PORT_CATEGORY = "excess_port_connections";
export const EXCESS_PORT_TEMPLATE_KEY = "error.excess_port_connections";

/**
 * registry を取得済みか。組み込みブロックが必ず含まれるので、空の索引は「未取得」
 * (取得中・取得失敗) とみなす。
 */
export function isRegistryLoaded(
  registry: RegistryIndex | null | undefined,
): registry is RegistryIndex {
  return registry !== undefined && registry !== null && registry.size > 0;
}

/** registry 取得済みで、その型が registry に無い (= プレースホルダ) か。 */
export function isPlaceholderType(
  type: string,
  registry: RegistryIndex | null | undefined,
): boolean {
  return isRegistryLoaded(registry) && !registry.has(type);
}

/** その型がユーザーブロックなら registry のメタデータ、それ以外は ``undefined``。 */
export function userBlockMetaOf(
  type: string,
  registry: RegistryIndex | null | undefined,
): BlockMetadata | undefined {
  const meta = registry?.get(type);
  return meta !== undefined && isUserBlock(meta) ? meta : undefined;
}

/**
 * ユーザーブロックの entry に残っているが registry の引数一覧に無い引数名 (entry の順)。
 *
 * @param params - entry の params。
 * @param meta - registry のメタデータ (ユーザーブロック)。
 */
export function removedParamNames(
  params: Record<string, unknown>,
  meta: BlockMetadata,
): string[] {
  const known = new Set(meta.params_spec.map((p) => p.name));
  return Object.keys(params).filter((k) => !known.has(k));
}

/**
 * Subsystem のように内部に ``params.blocks`` を持つ組み込みブロックか (再帰の対象)。
 * ユーザーブロック・プレースホルダは引数名が ``blocks`` でも潜らない。
 */
function innerScopeOf(
  block: BlockEntry,
  registry: RegistryIndex,
): { blocks: BlockEntry[]; connections: ConnectionEntry[] } | null {
  const meta = registry.get(block.type);
  if (meta === undefined || isUserBlock(meta)) return null;
  const params = block.params as Record<string, unknown>;
  if (!Array.isArray(params.blocks)) return null;
  return {
    blocks: params.blocks as BlockEntry[],
    connections: Array.isArray(params.connections)
      ? (params.connections as ConnectionEntry[])
      : [],
  };
}

function pruneBlocks(blocks: BlockEntry[], registry: RegistryIndex): BlockEntry[] {
  let changed = false;
  const next = blocks.map((b) => {
    const meta = userBlockMetaOf(b.type, registry);
    if (meta !== undefined) {
      const removed = removedParamNames(b.params, meta);
      if (removed.length === 0) return b;
      changed = true;
      const params = { ...b.params };
      for (const k of removed) delete params[k];
      return { ...b, params };
    }
    const inner = innerScopeOf(b, registry);
    if (inner === null) return b;
    const innerNext = pruneBlocks(inner.blocks, registry);
    if (innerNext === inner.blocks) return b;
    changed = true;
    return { ...b, params: { ...b.params, blocks: innerNext } };
  });
  return changed ? next : blocks;
}

/**
 * 消えた引数を除いたモデルを返す (ADR-0081 §論点 3)。保存時と実行要求の組み立て時に
 * 共通で使う 1 関数。
 *
 * - 対象は registry にある (= プレースホルダでない) ユーザーブロックだけ。組み込み
 *   ブロック・プレースホルダの entry は変えない
 * - Subsystem 内部 (``params.blocks``) も再帰で処理する
 * - registry 未取得なら何もしない。変更が無ければ**同じ参照**を返す
 *
 * @param model - 対象モデル (変更しない)。
 * @param registry - block registry の索引。
 * @returns 除去後のモデル (変更なしなら ``model`` そのもの)。
 */
export function pruneRemovedParams(
  model: FlwModel,
  registry: RegistryIndex | null | undefined,
): FlwModel {
  if (!isRegistryLoaded(registry)) return model;
  const blocks = pruneBlocks(model.blocks, registry);
  return blocks === model.blocks ? model : { ...model, blocks };
}

/** モデル中のブロック 1 件 (Subsystem 内部は ``qualifiedId`` が ``"sub/inner"``)。 */
export interface ModelBlockRef {
  blockId: string;
  qualifiedId: string;
  type: string;
}

/** registry のポート数を超える index に繋がった配線 1 本分。 */
export interface ExcessPortRef extends ModelBlockRef {
  direction: "in" | "out";
  portIndex: number;
}

function walkScopes(
  blocks: readonly BlockEntry[],
  connections: readonly ConnectionEntry[],
  registry: RegistryIndex,
  prefix: readonly string[],
  visit: (
    blocks: readonly BlockEntry[],
    connections: readonly ConnectionEntry[],
    prefix: readonly string[],
  ) => void,
): void {
  visit(blocks, connections, prefix);
  for (const b of blocks) {
    const inner = innerScopeOf(b, registry);
    if (inner !== null) {
      walkScopes(inner.blocks, inner.connections, registry, [...prefix, b.id], visit);
    }
  }
}

/**
 * モデルを再帰的に走査してプレースホルダを全部集める (文書順)。registry 未取得なら空。
 */
export function collectPlaceholderBlocks(
  model: FlwModel,
  registry: RegistryIndex | null | undefined,
): ModelBlockRef[] {
  if (!isRegistryLoaded(registry)) return [];
  const out: ModelBlockRef[] = [];
  walkScopes(model.blocks, model.connections, registry, [], (blocks, _c, prefix) => {
    for (const b of blocks) {
      if (!registry.has(b.type)) {
        out.push({ blockId: b.id, qualifiedId: [...prefix, b.id].join("/"), type: b.type });
      }
    }
  });
  return out;
}

/**
 * ユーザーブロックの registry のポート数を超える index に繋がった配線を全部集める。
 * プレースホルダ (ポート数が分からない) と組み込みブロックは対象外。
 */
export function collectExcessPortConnections(
  model: FlwModel,
  registry: RegistryIndex | null | undefined,
): ExcessPortRef[] {
  if (!isRegistryLoaded(registry)) return [];
  const out: ExcessPortRef[] = [];
  walkScopes(model.blocks, model.connections, registry, [], (blocks, connections, prefix) => {
    const byId = new Map(blocks.map((b) => [b.id, b]));
    const ref = (b: BlockEntry): ModelBlockRef => ({
      blockId: b.id,
      qualifiedId: [...prefix, b.id].join("/"),
      type: b.type,
    });
    for (const c of connections) {
      const dst = byId.get(c.dst);
      const dstMeta = dst && userBlockMetaOf(dst.type, registry);
      if (dst && dstMeta && c.dst_idx >= dstMeta.default_n_inputs) {
        out.push({ ...ref(dst), direction: "in", portIndex: c.dst_idx });
      }
      const src = byId.get(c.src);
      const srcMeta = src && userBlockMetaOf(src.type, registry);
      if (src && srcMeta && c.src_idx >= srcMeta.default_n_outputs) {
        out.push({ ...ref(src), direction: "out", portIndex: c.src_idx });
      }
    }
  });
  return out;
}

/** 消えた引数を持つユーザーブロック 1 件分。 */
export interface RemovedParamsRef extends ModelBlockRef {
  params: string[];
}

/**
 * registry から消えた引数を entry に残しているユーザーブロックを全部集める (Subsystem 内部も)。
 * ``pruneRemovedParams`` が除去する対象と同じ。registry 未取得なら空。
 */
export function collectRemovedParams(
  model: FlwModel,
  registry: RegistryIndex | null | undefined,
): RemovedParamsRef[] {
  if (!isRegistryLoaded(registry)) return [];
  const out: RemovedParamsRef[] = [];
  walkScopes(model.blocks, model.connections, registry, [], (blocks, _c, prefix) => {
    for (const b of blocks) {
      const meta = userBlockMetaOf(b.type, registry);
      if (meta === undefined) continue;
      const params = removedParamNames(b.params, meta);
      if (params.length > 0) {
        out.push({
          blockId: b.id,
          qualifiedId: [...prefix, b.id].join("/"),
          type: b.type,
          params,
        });
      }
    }
  });
  return out;
}

/** 消えた引数の一覧をトーストに並べる件数の上限 (超えた分は ``…``)。 */
export const MAX_REMOVED_PARAMS_SHOWN = 5;

/**
 * 消えた引数の一覧を 1 行の文字列にする (``"a (bias), sub/b (x, y), …"``)。
 * ブロック id・引数名はモデルファイル由来なので整形する。
 */
export function formatRemovedParams(refs: readonly RemovedParamsRef[]): string {
  const shown = refs
    .slice(0, MAX_REMOVED_PARAMS_SHOWN)
    .map(
      (r) =>
        `${cleanServerText(r.qualifiedId, MAX_LABEL_CHARS)} (${r.params
          .map((p) => cleanServerText(p, MAX_LABEL_CHARS))
          .join(", ")})`,
    );
  if (refs.length > MAX_REMOVED_PARAMS_SHOWN) shown.push("…");
  return shown.join(", ");
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)];
}

/** 超過ポートの表示ラベル (``"sub/a.in[2]"``)。 */
export function formatExcessPort(ref: ExcessPortRef): string {
  return `${ref.qualifiedId}.${ref.direction}[${ref.portIndex}]`;
}

function failure(
  category: string,
  templateKey: string,
  templateArgs: Record<string, unknown>,
  refs: readonly ModelBlockRef[],
  message: string,
): FailurePayload {
  const first = refs[0];
  return {
    category,
    template_key: templateKey,
    template_args: { ...templateArgs, message },
    block_id: first?.blockId ?? null,
    block_ids: unique(refs.map((r) => r.blockId)),
    block_type: first?.type ?? null,
    block_label: first?.qualifiedId ?? null,
    t: null,
    raw_message: message,
    raw_traceback: null,
  };
}

/**
 * 実行前チェック (ADR-0081 §4-B の 1)。プレースホルダ・超過ポートの配線があれば、
 * 実行要求を送らずにログタブへ出す ``FailurePayload`` を返す (問題が無ければ ``null``)。
 *
 * プレースホルダは backend の 400 ``unknown_block_type`` と同じ形 (同じ i18n 文言) にする。
 *
 * @param model - 実行しようとしているモデル。
 * @param registry - block registry の索引 (未取得ならチェックしない)。
 */
export function runPrecheckFailure(
  model: FlwModel,
  registry: RegistryIndex | null | undefined,
): FailurePayload | null {
  const placeholders = collectPlaceholderBlocks(model, registry);
  if (placeholders.length > 0) {
    const types = unique(placeholders.map((p) => p.type));
    const labels = placeholders.map((p) => p.qualifiedId);
    return failure(
      UNKNOWN_BLOCK_TYPE_CATEGORY,
      UNKNOWN_BLOCK_TYPE_TEMPLATE_KEY,
      {
        types,
        blocks: placeholders.map((p) => ({
          block_id: p.blockId,
          qualified_id: p.qualifiedId,
          type: p.type,
        })),
        block_labels: labels,
        truncated: false,
      },
      placeholders,
      `The model uses block types that are not loaded: ${types.join(", ")}. ` +
        `Fix or reload the blocks, or remove these blocks: ${labels.join(", ")}.`,
    );
  }
  const excess = collectExcessPortConnections(model, registry);
  if (excess.length > 0) {
    const ports = excess.map(formatExcessPort);
    return failure(
      EXCESS_PORT_CATEGORY,
      EXCESS_PORT_TEMPLATE_KEY,
      { ports, block_labels: unique(excess.map((e) => e.qualifiedId)) },
      excess,
      `Connections go to ports that the blocks no longer have: ${ports.join(", ")}.`,
    );
  }
  return null;
}

/**
 * registry のポート名 (``input_names`` / ``output_names``) を整形する (無名・欠落は ``""``)。
 *
 * @param names - registry のポート名 (信頼できない文字列、v2 以前のサーバでは欠落)。
 */
export function userPortNames(names: readonly unknown[] | undefined): string[] {
  return (names ?? []).map((n) => cleanServerText(n, MAX_LABEL_CHARS));
}

/**
 * プレースホルダに出す型名 (整形済み。長ければ末尾を残して先頭を ``…`` で切る)。
 *
 * @param type - モデルの型名 (信頼できない文字列)。
 */
export function placeholderTypeLabel(type: string): string {
  const chars = Array.from(cleanServerText(type, MAX_PATH_CHARS));
  if (chars.length <= PLACEHOLDER_TYPE_LABEL_CHARS) return chars.join("");
  return ELLIPSIS + chars.slice(chars.length - PLACEHOLDER_TYPE_LABEL_CHARS + 1).join("");
}

// ---------------------------------------------------------------------------
// セッション中に一度 registry で見たユーザーブロックのメタデータ (ADR-0081 §4-B)。
// 再読み込みで型が消えた直後でも、プレースホルダを直前のポート数・ポート名で描いて
// 形を崩さない。モデルには書かない。
// ---------------------------------------------------------------------------

const lastSeen = new Map<string, BlockMetadata>();

/** registry で見たユーザーブロックのメタデータを記憶する (同じ型は上書き)。 */
export function rememberBlockMetadata(blocks: readonly BlockMetadata[]): void {
  for (const b of blocks) {
    if (isUserBlock(b)) lastSeen.set(b.type_path, b);
  }
}

/** 記憶しているメタデータ (type_path → メタデータ)。 */
export function lastSeenBlockMetadata(): RegistryIndex {
  return lastSeen;
}

/** @internal テスト用: 記憶を消す。 */
export function _resetLastSeenBlockMetadataForTest(): void {
  lastSeen.clear();
}
