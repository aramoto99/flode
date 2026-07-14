// ADR-0041 §論点 11-A: 外部エディタによる ``.flw.json`` 書き換えを 5 秒
// polling で検知する hook。
//
// 動作仕様:
//   1. ``selectedFilePath`` が non-null かつシミュレーション実行中でないとき、
//      5 秒ごとに **条件付き GET** (``If-None-Match: <editingFileEtag>``) で
//      対象ファイルを確認。変更なしならサーバは 304 (本文なし) を返す
//   2. 304 → 何もしない (= 変更なし。全文ダウンロードは発生しない)
//   3. 200 (= etag が異なる) + ``dirty == false`` → silent reload (= editingModel
//      を新内容で上書き、利用者は気づかなくて OK)
//   4. 200 + ``dirty == true`` → dialog.confirm で利用者に選択を問う:
//      - OK: 外部変更を取り込む (= 自分の変更を破棄して reload)
//      - Cancel: 自分の変更を残す (= 次回保存時に etag mismatch 409 で再衝突
//        するが、利用者は明示的に選んだので OK)
//   5. タブが非表示 (``document.hidden``) の間は tick を skip し、再表示時に
//      即時 tick する (= バックグラウンドタブが無駄にポーリングしない。
//      README の「changes appear on next focus」と整合)
//
// 5 秒間隔はリファレンス Web IDE の既定と整合 (ADR-0041 §論点 11-A 採択案)。OS 別
// file watcher は実装複雑度の割にメリットが薄いため採用しない (= polling で
// 十分、§Risks #5 と整合)。

import { useEffect, useRef } from "react";

import { getFileContentIfChanged } from "../api/filesApi";
import { dialog } from "./dialogService";
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
      // バックグラウンドタブではポーリングしない (再表示時に即時 tick する)
      if (typeof document !== "undefined" && document.hidden) return;
      inFlightRef.current = true;
      try {
        const state = useAppStore.getState();
        const path = state.selectedFilePath;
        // path が変わっていたら abort (= 切替後の polling は新 effect が担当)
        if (path !== selectedFilePath) return;
        // 条件付き GET: ローカル etag と一致なら 304 (= null) が返り本文なし。
        // etag 未確定 (null) の間は比較材料が無いので tick 自体を skip する。
        const localEtagAtRequest = state.editingFileEtag;
        if (localEtagAtRequest === null) return;
        const resp = await getFileContentIfChanged(path, localEtagAtRequest);
        if (cancelled) return;
        if (resp === null) return; // 304 = 変化なし
        const latestState = useAppStore.getState();
        // tick 中に利用者がファイルを切り替えた場合はもう apply しない
        if (latestState.selectedFilePath !== path) return;
        const localEtag = latestState.editingFileEtag;
        if (localEtag === resp.etag) return; // 変化なし (tick 中に自分が保存した等)
        // 外部変更検知
        if (!latestState.dirty) {
          // silent reload (= 利用者は何も編集していないのでサーバ最新を反映)
          latestState.setEditingModel(resp.content);
          latestState.setEditingFileMeta(resp.mtime, resp.etag);
          // setDirty(false) — setEditingModel は dirty を変えないので明示
          latestState.setDirty(false);
          return;
        }
        // dirty + 外部変更 → 利用者に確認 (v0.32.0: dialog.confirm に置換、
        // 旧 window.confirm は blocking で polling tick を停止していたが、
        // dialog.confirm は非 blocking。複数 dialog の同時表示を防ぐため、
        // dialogService 内部の queue が順次表示してくれる)。
        const accept = await dialog.confirm(
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
    // タブ再表示で即時 tick (= 非表示中に溜まった外部変更をすぐ反映)
    const onVisible = (): void => {
      if (!document.hidden) void tick();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [selectedFilePath, editingFileEtag, status]);
}
