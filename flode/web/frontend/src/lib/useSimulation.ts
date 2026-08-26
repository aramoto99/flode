// シミュレーション開始 / 停止 + WebSocket ストリーミングを 1 か所に集約する hook。
// Toolbar の Run/Stop ボタンと SimulationControls の進捗表示で共通使用する。
//
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``selectedModelId`` / ``--model-dir`` /
// ``startSimulation(model_id)`` 経路は削除済。``selectedFilePath`` セット時のみ
// File API 経路 (= 保存 → model_path body で start) で動く。

import { useEffect, useRef } from "react";

import {
  ApiError,
  getSimulationResults,
  startSimulationByPath,
  stopSimulation,
} from "../api/client";
import { putFileContent } from "../api/filesApi";
import { streamSimulation } from "../api/stream";
import { useAppStore } from "../store/appStore";
import { pushToast } from "../store/toastStore";
import i18n from "../i18n";
import { dialog } from "./dialogService";
import { startWithPythonGate } from "./pythonTrust";

/**
 * 終端後 backfill を実施済みの simulation_id。useSimulation は Toolbar と
 * SimulationControls の 2 箇所でマウントされるため、module-level で重複 fetch
 * を防ぐ (simulation_id は run ごとに一意)。
 */
let backfilledSimId: string | null = null;

/**
 * WS ストリームは内部 queue (max 1024) 満杯時に古い ``scope_batch`` を drop
 * するため、ライブ描画した波形は欠損している可能性がある。終端後に
 * ``GET /results`` の一括データで scope バッファを置き換え、表示を正にする。
 */
async function backfillScopeResults(simId: string): Promise<void> {
  try {
    const results = await getSimulationResults(simId);
    const state = useAppStore.getState();
    // fetch 中に次の run が始まっていたら破棄 (新 run のバッファを壊さない)
    if (state.simulationId !== simId || state.status === "running") return;
    state.replaceScopes(results.scopes);
  } catch (e) {
    // backfill は WS ライブ表示に対する冗長系。失敗してもライブ描画分は
    // 残っているため UI は壊さず、原因調査用にログのみ残す。
    console.warn(`Scope results backfill failed for ${simId}`, e);
  }
}

export function useSimulation(): {
  run: () => Promise<void>;
  stop: () => Promise<void>;
} {
  const wsRef = useRef<WebSocket | null>(null);
  const status = useAppStore((s) => s.status);
  const simulationId = useAppStore((s) => s.simulationId);
  const startedSimulation = useAppStore((s) => s.startedSimulation);
  const handleStreamMessage = useAppStore((s) => s.handleStreamMessage);

  // アンマウント or 終了状態で WS を閉じる
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);
  useEffect(() => {
    if (status === "completed" || status === "stopped" || status === "failed") {
      wsRef.current?.close();
      wsRef.current = null;
      // 終端したら完全な結果で波形を置き換える (WS drop 分の補完)。
      if (simulationId !== null && backfilledSimId !== simulationId) {
        backfilledSimId = simulationId;
        void backfillScopeResults(simulationId);
      }
    }
  }, [status, simulationId]);

  const run = async (): Promise<void> => {
    const state = useAppStore.getState();
    const model = state.editingModel;
    if (!model) return;
    if (state.selectedFilePath === null) return;
    try {
      // Run 前に最新を保存 (= 「保存してから実行」セマンティクス、editingFileEtag
      // を使った楽観ロックで race を検知)。
      const resp = await putFileContent(
        state.selectedFilePath,
        model,
        state.editingFileEtag ?? undefined,
      );
      state.setEditingFileMeta(resp.mtime, resp.etag);
      state.setDirty(false);
      // SPEC-0023 / ADR-0073 §論点 4 (S): PythonFunction を含むモデルは初回のみ
      // 確認ダイアログ (承認 digest は localStorage、コード変更で自動失効)。
      // これは UX 機構であってセキュリティ機構ではない (hard gate はサーバ側)。
      const filePath = state.selectedFilePath;
      const started = await startWithPythonGate(
        (ack) => startSimulationByPath(filePath, ack),
        {
          workspaceHash: state.workspaceHash,
          modelPath: filePath,
          confirm: (info) =>
            dialog.confirm(
              i18n.t("python_function.confirm.message", {
                blocks: info.blockLabels.join(", "),
              }),
              {
                title: i18n.t("python_function.confirm.title"),
                okLabel: i18n.t("python_function.confirm.ok"),
                variant: "danger",
              },
            ),
        },
      );
      if (started === null) return; // ユーザーがキャンセル (= 失敗ではない)
      const { simulation_id } = started;
      startedSimulation(simulation_id);
      const ws = streamSimulation(simulation_id, handleStreamMessage);
      wsRef.current?.close();
      wsRef.current = ws;
    } catch (e) {
      console.error("Failed to start simulation", e);
      // ADR-0056 §F3: start REST が構造化 detail (= FailurePayload) を返した場合、
      // Error tab に表示するため lastFailure にセットする。それ以外 (= 通信エラー
      // 等) は generic な FailurePayload を組み立てる (= 起動失敗 source 固定)。
      const setLastFailure = useAppStore.getState().setLastFailure;
      if (e instanceof ApiError && e.structured !== null) {
        setLastFailure(e.structured, "start");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        setLastFailure(
          {
            category: "unknown",
            template_key: "error.unknown",
            template_args: { raw_message: msg },
            block_id: null,
            block_ids: [],
            block_type: null,
            block_label: null,
            t: null,
            raw_message: msg,
            raw_traceback: null,
          },
          "start",
        );
      }
    }
  };

  const stop = async (): Promise<void> => {
    if (!simulationId) return;
    try {
      await stopSimulation(simulationId);
    } catch (e) {
      console.error("Failed to stop simulation", e);
      // 停止要求の失敗はユーザー操作への無反応になるため toast で通知する
      // (WS 切断等でどのみち止まるケースも多いが、黙殺はしない)。
      pushToast({
        severity: "error",
        message: i18n.t("simulation.stop_failed", {
          defaultValue: "Stop request failed: {{message}}",
          message: e instanceof Error ? e.message : String(e),
        }),
      });
    }
  };

  return { run, stop };
}
