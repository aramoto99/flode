// ADR-0041 §論点 11-A: 外部エディタによる ``.flw.json`` 書き換えを 5 秒
// polling で検知する hook。
//
// 動作仕様:
//   1. ``selectedFilePath`` が non-null かつシミュレーション実行中でないとき、
//      5 秒ごとに ``GET /api/v1/files/content`` で対象ファイルの etag を確認
//   2. etag が ``editingFileEtag`` と一致 → 何もしない (= 変更なし)
//   3. etag が異なる + ``dirty == false`` → silent reload (= editingModel を
//      新内容で上書き、利用者は気づかなくて OK)
//   4. etag が異なる + ``dirty == true`` → ``window.confirm`` で利用者に選択を
//      問う:
//      - OK: 外部変更を取り込む (= 自分の変更を破棄して reload)
//      - Cancel: 自分の変更を残す (= 次回保存時に etag mismatch 409 で再衝突
//        するが、利用者は明示的に選んだので OK)
//
// 5 秒間隔は JupyterLab 既定と整合 (ADR-0041 §論点 11-A 採択案)。OS 別
// file watcher は実装複雑度の割にメリットが薄いため採用しない (= polling で
// 十分、§Risks #5 と整合)。
//
// 本格的な 3-button モーダルは v0.20.0 で実装予定。v0.19.0 では window.confirm
// ベースで動作のみ確実にする。

import { useEffect, useRef } from "react";

import { getFileContent } from "../api/filesApi";
import { useAppStore } from "../store/appStore";

export const EXTERNAL_POLL_INTERVAL_MS = 5000;

/**
 * ``selectedFilePath`` の外部変更を 5 秒 polling で検知する hook。
 * App ルートで 1 度だけ mount する想定。
 */
export function useExternalChangesPoll(): void {
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const editingFileEtag = useAppStore((s) => s.editingFileEtag);
  const status = useAppStore((s) => s.status);

  // ``poll`` 関数自体は store の最新値を読むので deps から除外する。useRef で
  // 直近の ``selectedFilePath`` を保持し、polling の中で stale closure を回避。
  const inFlightRef = useRef<boolean>(false);

  useEffect(() => {
    // simulation 実行中は polling しない (= 終了後の auto-reload で十分)
    if (selectedFilePath === null || status === "running") return;

    let cancelled = false;

    const tick = async (): Promise<void> => {
      if (cancelled || inFlightRef.current) return;
      inFlightRef.current = true;
      try {
        const state = useAppStore.getState();
        const path = state.selectedFilePath;
        // path が変わっていたら abort (= 切替後の polling は新 effect が担当)
        if (path !== selectedFilePath) return;
        const resp = await getFileContent(path);
        if (cancelled) return;
        const latestState = useAppStore.getState();
        // tick 中に利用者がファイルを切り替えた場合はもう apply しない
        if (latestState.selectedFilePath !== path) return;
        const localEtag = latestState.editingFileEtag;
        if (localEtag === resp.etag) return; // 変化なし
        // 外部変更検知
        if (!latestState.dirty) {
          // silent reload (= 利用者は何も編集していないのでサーバ最新を反映)
          latestState.setEditingModel(resp.content);
          latestState.setEditingFileMeta(resp.mtime, resp.etag);
          // setDirty(false) — setEditingModel は dirty を変えないので明示
          latestState.setDirty(false);
          return;
        }
        // dirty + 外部変更 → 利用者に確認 (window.confirm 簡易版)
        // confirm ダイアログは alert と違って blocking、polling tick の
        // setInterval は呼び出されない (= 多重ダイアログ防止)。
        const accept = window.confirm(
          `"${path}" was modified externally.\n` +
            "OK: discard your unsaved changes and reload\n" +
            "Cancel: keep your version (next save will overwrite the external changes)",
        );
        if (cancelled) return;
        const finalState = useAppStore.getState();
        if (finalState.selectedFilePath !== path) return;
        if (accept) {
          finalState.setEditingModel(resp.content);
          finalState.setEditingFileMeta(resp.mtime, resp.etag);
          finalState.setDirty(false);
        }
        // Cancel: 何もしない (= dirty 維持、次回保存で 409 になる可能性あり、
        // useAutoSave 側で current_etag を最新 etag に更新する fallback も
        // 検討余地ありだが本 hook は read-only)
      } catch (e) {
        // 404 (= 外部削除) や 503 など。ログのみ、UX はそのまま。
        console.warn("External poll failed:", e);
      } finally {
        inFlightRef.current = false;
      }
    };

    const intervalId = setInterval(() => void tick(), EXTERNAL_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [selectedFilePath, editingFileEtag, status]);
}
