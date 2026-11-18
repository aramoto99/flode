// ADR-0081 §論点 3 / §4-B (U5): モデルを backend に渡す直前 (保存・実行要求の組み立て) の処理。
//
// - 消えた引数の除去は保存と実行で共通の 1 関数 ``pruneRemovedParams`` を使う。実行は
//   「保存してから model_path で開始」なので、実行要求の組み立ても同じ経路を通る
// - 保存時は画面上のモデルからも除去する (undo には積まない。``_migrated_from`` 除去と同じ扱い)
// - 除去したら warning トーストで知らせる (同じブロック・引数の組はセッション中 1 回)
// - 実行前チェック (プレースホルダ・超過ポート) は要求を送る前に行う
//
// block registry は react-query の cache (``BLOCKS_REGISTRY_QUERY_KEY``) から読む。
// 除去・チェックは「最新の取得に成功した registry」でだけ行う: 取得中 (再取得・invalidate 済み)
// や失敗時は何もしない (保存はそのまま、backend の 400 が最終防衛)。古い registry で
// 引数を消してしまわないため。

import i18n from "../i18n";
import { useAppStore } from "../store/appStore";
import { pushToast } from "../store/toastStore";
import type { BlockRegistryResponse, FailurePayload, FlwModel } from "../types/api";
import { indexRegistry } from "./portShapeValidate";
import { queryClient } from "./queryClient";
import { BLOCKS_REGISTRY_QUERY_KEY } from "./queryKeys";
import { reconcileSignalNames } from "./signalNames";
import { collectDynamicUserBlocks, ensureUserBlockPorts } from "./userBlockPorts";
import {
  collectRemovedParams,
  formatRemovedParams,
  pruneRemovedParams,
  runPrecheckFailure,
  type RegistryIndex,
} from "./userBlockModel";

/**
 * 最新の取得に成功した block registry の索引。取得中・invalidate 済み・失敗・未取得なら
 * ``undefined`` (除去・実行前チェックをしない)。
 */
export function freshRegistryIndex(): RegistryIndex | undefined {
  const state = queryClient.getQueryState<BlockRegistryResponse>(BLOCKS_REGISTRY_QUERY_KEY);
  if (
    state === undefined ||
    state.status !== "success" ||
    state.fetchStatus === "fetching" ||
    state.isInvalidated ||
    state.data === undefined
  ) {
    return undefined;
  }
  return indexRegistry(state.data.blocks);
}

/** セッション中に除去を知らせた (ブロック id, 引数名) の組。 */
const notifiedRemovals = new Set<string>();

/** @internal テスト用: 知らせた組の記憶を消す。 */
export function _resetRemovalNoticesForTest(): void {
  notifiedRemovals.clear();
}

/**
 * 保存・実行要求の組み立てに使うモデルを返す (消えた引数を除去)。
 *
 * ``model`` が画面上のモデル (``editingModel``) そのものなら、除去後のモデルで置き換える
 * (dirty・undo 履歴は変えない)。保存先 (Save As 等) が別でも除去は同じ規則で行う。
 * 実際に除去したら、まだ知らせていない組があるときだけ warning トーストを出す。
 *
 * @param model - 保存・実行しようとしているモデル。
 * @returns backend に送るモデル (除去が無ければ ``model`` そのもの)。
 */
export function prepareModelForBackend(model: FlwModel): FlwModel {
  // ADR-0087 論点 4: 読み込んだファイルにあった孤児・不正な信号名を、全スコープで消す
  // (開いただけでは書き換えず、次の保存・実行で消す。履歴は積まない)
  const reconciled = reconcileSignalNames(null, model);
  if (reconciled !== model && useAppStore.getState().editingModel === model) {
    useAppStore.setState({ editingModel: reconciled });
  }
  return pruneParamsForBackend(reconciled);
}

function pruneParamsForBackend(model: FlwModel): FlwModel {
  const registry = freshRegistryIndex();
  const pruned = pruneRemovedParams(model, registry);
  if (pruned === model) return model;
  const removed = collectRemovedParams(model, registry);
  const keys = removed.flatMap((r) => r.params.map((p) => `${r.qualifiedId}\u0000${p}`));
  if (keys.some((k) => !notifiedRemovals.has(k))) {
    keys.forEach((k) => notifiedRemovals.add(k));
    pushToast({
      severity: "warning",
      message: i18n.t("user_blocks.params_removed_on_save", {
        count: removed.length,
        list: formatRemovedParams(removed),
      }),
    });
  }
  if (useAppStore.getState().editingModel === model) {
    useAppStore.setState({ editingModel: pruned });
  }
  return pruned;
}

/**
 * 実行前チェックの前に、ポートが引数で変わるユーザーブロックのポートの解決を待つ上限 (ms)。
 * サーバが応答しないときはここで諦め、そのブロックの超過ポートの判定は飛ばして backend の
 * 読み込み時の検査 (``ModelLoadError``) に任せる。
 */
export const PRECHECK_PORTS_WAIT_MS = 5_000;

/**
 * ポートが引数で変わるユーザーブロックのポートの解決を待つ (上限 ``PRECHECK_PORTS_WAIT_MS``)。
 * 応答待ちの同じ問い合わせには合流する (``ensureUserBlockPorts`` の inflight)。通信失敗・タイム
 * アウトは握りつぶす (そのブロックは未解決のまま = 実行前チェックでは超過と断定しない)。
 *
 * @param model - 実行しようとしているモデル。
 */
export async function awaitUserBlockPortsForRun(model: FlwModel): Promise<void> {
  let requests: ReturnType<typeof collectDynamicUserBlocks>;
  try {
    requests = collectDynamicUserBlocks(model, freshRegistryIndex());
  } catch (e) {
    // 待てなくても実行は止めない (判定は backend の読み込み時の検査に任せる)
    console.warn("Could not collect user blocks with dynamic ports before run", e);
    return;
  }
  if (requests.length === 0) return;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<void>((resolve) => {
    timer = setTimeout(resolve, PRECHECK_PORTS_WAIT_MS);
  });
  try {
    await Promise.race([ensureUserBlockPorts(requests).catch(() => undefined), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 実行前チェック (ADR-0081 §4-B の 1)。読み込めないブロック・超過ポートの配線があれば
 * ログタブに出す ``FailurePayload`` を返す (問題が無ければ ``null``)。
 *
 * ポートが引数で変わるユーザーブロックのポートは、先に ``awaitUserBlockPortsForRun`` で解決を
 * 待っておくこと (未解決のままだと、そのブロックの超過ポートは判定しない)。
 *
 * @param model - 実行しようとしているモデル。
 */
export function precheckRun(model: FlwModel): FailurePayload | null {
  return runPrecheckFailure(model, freshRegistryIndex());
}
