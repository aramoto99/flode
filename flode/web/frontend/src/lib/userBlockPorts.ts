// ポート数・ポート名が引数で変わるユーザーブロック (registry の ``dynamic_ports``、クラス属性
// ``block_dynamic_ports = True``) の、引数ごとのポートのクライアント側キャッシュ。
//
// - サーバ (``POST /api/v1/blocks/resolve-port-shapes``) が ``cls(**params)`` したインスタンスの
//   ポート数・宣言 shape・ポート名を返す。frontend は再計算しない (二重実装しない)
// - key は ``type_path`` + 引数の安定 JSON (キー順を揃える)。同じ引数は同じポートなので
//   block id に依存しない
// - ``resolvePortCounts`` 等 (同期・純関数) から読めるよう module-level Map で持つ。解決の完了は
//   ``subscribeUserBlockPorts`` で通知し、React 側は ``useUserBlockPortsVersion`` で再描画する
//   (PythonFunction の ``pythonFunctionSpec.ts`` と同じ仕組み)。未解決の間は registry の既定値
// - モデル JSON には保存しない (導出データの二重書き手を作らない)

import { ApiError, resolvePortShapes } from "../api/client";
import type { BlockEntry, BlockMetadata, FlwModel } from "../types/api";
import { isUserBlock } from "./userBlocks";

/** 引数を与えたときのユーザーブロックのポート。 */
export interface UserBlockPorts {
  nInputs: number;
  nOutputs: number;
  shapesIn: number[][];
  shapesOut: number[][];
  /** ポート名 (空配列 = 無名。信頼できない文字列なので表示側で整形する)。 */
  inputNames: string[];
  outputNames: string[];
}

/** 解決を問い合わせる 1 件 (型名と引数)。 */
export interface UserBlockPortsRequest {
  type_path: string;
  params: Record<string, unknown>;
}

/** サーバが引数を拒否した (400 / 404) 結果も覚えて、同じ引数で問い合わせ続けない。 */
type CacheEntry = { ok: true; ports: UserBlockPorts } | { ok: false; error: string };

/** キャッシュの上限 (入力途中の値ごとに増えるので、超えたら古いものから捨てる)。 */
export const MAX_USER_BLOCK_PORTS_CACHE = 500;

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();
let version = 0;
/** キャッシュの世代。破棄のたびに進め、破棄前に出した問い合わせの応答を捨てる。 */
let generation = 0;

function notify(): void {
  version += 1;
  for (const l of listeners) l();
}

/**
 * キー順を揃えた JSON (同じ引数なら同じ文字列)。
 *
 * @param value - JSON 値 (モデルの params)。
 */
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    return `{${Object.keys(obj)
      .sort()
      .filter((k) => obj[k] !== undefined)
      .map((k) => `${JSON.stringify(k)}:${stableJson(obj[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/**
 * キャッシュのキー (``type_path`` + 引数の安定 JSON)。``params`` が無い (モデル JSON で省略) ときは
 * ``{}`` とみなす (収集側 ``collectDynamicUserBlocks`` の ``b.params ?? {}`` とキーを一致させる)。
 *
 * @param typePath - ブロックの型名。
 * @param params - ブロックの引数。
 */
export function userBlockPortsKey(
  typePath: string,
  params: Record<string, unknown> | undefined,
): string {
  return `${typePath}\u0000${stableJson(params ?? {})}`;
}

/**
 * ポートが引数で変わるユーザーブロックか (registry の ``dynamic_ports``)。
 *
 * @param meta - registry のメタデータ (未取得なら undefined)。
 */
export function isDynamicUserBlock(meta: BlockMetadata | undefined): meta is BlockMetadata {
  return meta !== undefined && isUserBlock(meta) && meta.dynamic_ports === true;
}

/**
 * 同期取得。未解決 (問い合わせ前・応答待ち)、またはサーバが引数を拒否したなら ``undefined``。
 *
 * @param typePath - ブロックの型名。
 * @param params - ブロックの引数。
 */
export function getCachedUserBlockPorts(
  typePath: string,
  params: Record<string, unknown>,
): UserBlockPorts | undefined {
  const entry = cache.get(userBlockPortsKey(typePath, params));
  return entry?.ok === true ? entry.ports : undefined;
}

/** 通知購読 (``useSyncExternalStore`` 用)。 */
export function subscribeUserBlockPorts(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 現在のキャッシュ世代 (``useSyncExternalStore`` の snapshot)。 */
export function getUserBlockPortsVersion(): number {
  return version;
}

function store(key: string, entry: CacheEntry): void {
  cache.delete(key);
  cache.set(key, entry);
  while (cache.size > MAX_USER_BLOCK_PORTS_CACHE) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

async function fetchOne(key: string, req: UserBlockPortsRequest): Promise<void> {
  const gen = generation;
  try {
    const r = await resolvePortShapes(req.type_path, req.params);
    // 応答待ちの間にブロックが再読み込みされた: 古いコードの結果なので覚えない
    if (gen !== generation) return;
    store(key, {
      ok: true,
      ports: {
        nInputs: r.n_inputs,
        nOutputs: r.n_outputs,
        shapesIn: r.port_shapes_in,
        shapesOut: r.port_shapes_out,
        inputNames: stringList(r.input_names),
        outputNames: stringList(r.output_names),
      },
    });
  } catch (e) {
    // 引数の拒否 (400) / 型が無い (404) は同じ引数で何度聞いても同じなので覚える。
    // 通信失敗などはキャッシュしない (= 次の要求で再試行)
    if (gen !== generation) return;
    if (e instanceof ApiError && (e.status === 400 || e.status === 404)) {
      store(key, { ok: false, error: e.message });
    } else {
      return;
    }
  } finally {
    if (gen === generation) inflight.delete(key);
  }
  notify();
}

/**
 * 未キャッシュの (型名, 引数) をサーバに問い合わせる。同じキーの同時要求は 1 回にまとめる。
 * 解決時点で ``requests`` は全てキャッシュ済み (通信失敗したものを除く)。
 *
 * @param requests - 問い合わせる型名と引数。
 */
export async function ensureUserBlockPorts(
  requests: Iterable<UserBlockPortsRequest>,
): Promise<void> {
  const waits: Promise<void>[] = [];
  const seen = new Set<string>();
  for (const req of requests) {
    const key = userBlockPortsKey(req.type_path, req.params);
    if (seen.has(key)) continue;
    const hit = cache.get(key);
    if (hit !== undefined) {
      store(key, hit); // まだ使われているキーを新しい側へ (古い順に捨てるときに残す)
      continue;
    }
    seen.add(key);
    let p = inflight.get(key);
    if (p === undefined) {
      p = fetchOne(key, req);
      inflight.set(key, p);
    }
    waits.push(p);
  }
  await Promise.all(waits);
}

/**
 * モデル (Subsystem 内部を再帰) から、ポートが引数で変わるユーザーブロックの
 * (型名, 引数) を集める。ユーザーブロックの引数 ``blocks`` には潜らない。
 *
 * @param model - 対象モデル。
 * @param registry - block registry の索引 (未取得なら空を返す)。
 */
export function collectDynamicUserBlocks(
  model: FlwModel | null | undefined,
  registry: ReadonlyMap<string, BlockMetadata> | undefined,
): UserBlockPortsRequest[] {
  const out: UserBlockPortsRequest[] = [];
  if (registry === undefined) return out;
  const walk = (blocks: unknown): void => {
    if (!Array.isArray(blocks)) return;
    for (const b of blocks as BlockEntry[]) {
      if (!b || typeof b !== "object") continue;
      const meta = registry.get(b.type);
      const params = (b.params ?? {}) as Record<string, unknown>;
      if (isDynamicUserBlock(meta)) {
        out.push({ type_path: b.type, params });
        continue;
      }
      if (meta !== undefined && isUserBlock(meta)) continue;
      if (Array.isArray(params.blocks)) walk(params.blocks);
    }
  };
  walk(model?.blocks);
  return out;
}

/**
 * 超過ポートの判定 (実行前チェック・配線の赤表示・Inspector の警告) に使ってよいポート。
 * ポートが引数で変わるユーザーブロックで、その引数のポートがまだ分からない (問い合わせ前・
 * 応答待ち・通信失敗でキャッシュが無い) ときは ``undefined`` (分からない)。それ以外は
 * ``effectiveUserBlockPorts`` と同じ (固定ポート、解決済み、サーバが引数を拒否した (400 / 404)
 * なら registry の既定値)。
 *
 * 未解決の間 ``effectiveUserBlockPorts`` が返す registry の既定値は引数を反映していないので、
 * それと比べると引数で増えたポートの配線を超過と誤判定する
 * (bug-report 2026-11-19-run-precheck-unresolved-dynamic-ports)。
 *
 * @param meta - registry のメタデータ (ユーザーブロック)。
 * @param params - ブロックの引数。
 */
export function knownUserBlockPorts(
  meta: BlockMetadata,
  params: Record<string, unknown> | undefined,
): UserBlockPorts | undefined {
  if (isDynamicUserBlock(meta) && !cache.has(userBlockPortsKey(meta.type_path, params))) {
    return undefined;
  }
  return effectiveUserBlockPorts(meta, params ?? {});
}

/**
 * ユーザーブロックの、引数を反映したポート。``dynamic_ports`` でキャッシュ済みなら
 * その値、それ以外 (固定ポート・未解決・引数の拒否) は registry の既定値。
 *
 * @param meta - registry のメタデータ (ユーザーブロック)。
 * @param params - ブロックの引数。
 */
export function effectiveUserBlockPorts(
  meta: BlockMetadata,
  params: Record<string, unknown>,
): UserBlockPorts {
  if (isDynamicUserBlock(meta)) {
    const cached = getCachedUserBlockPorts(meta.type_path, params);
    if (cached !== undefined) return cached;
  }
  return {
    nInputs: meta.default_n_inputs,
    nOutputs: meta.default_n_outputs,
    shapesIn: meta.port_shapes_in_default,
    shapesOut: meta.port_shapes_out_default,
    inputNames: meta.input_names ?? [],
    outputNames: meta.output_names ?? [],
  };
}

/**
 * キャッシュを捨てる。ユーザーブロックを再読み込みしたとき (= 同じ引数でもポートが変わりうる、
 * 前に拒否された引数が通るようになりうる) に block registry と一緒に呼ぶ。
 */
export function invalidateUserBlockPorts(): void {
  generation += 1;
  cache.clear();
  inflight.clear();
  notify();
}

/** @internal テスト用: キャッシュを空にする。 */
export function _resetUserBlockPortsForTest(): void {
  invalidateUserBlockPorts();
}
