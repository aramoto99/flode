// ADR-0019 §(5): editingModel の dirty を 500 ms debounce で PUT する hook。
// Ctrl+S / beforeunload で即時 PUT も併用。
//
// v0.21.0 (ADR-0041 §論点 4-A): legacy ``selectedModelId`` / ``/api/v1/models/*``
// 経路は削除済。``selectedFilePath`` 配下の File API (PUT /api/v1/files/content)
// 一本化。

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { putFileContent } from "../api/filesApi";
import { useAppStore } from "../store/appStore";

export const AUTO_SAVE_DEBOUNCE_MS = 500;

/**
 * editingModel の変更を監視し、debounce 後に PUT を発射する。
 * Ctrl+S で即時 PUT、beforeunload で best-effort 保存。
 */
export function useAutoSave(): void {
  const editingModel = useAppStore((s) => s.editingModel);
  const dirty = useAppStore((s) => s.dirty);
  const setDirty = useAppStore((s) => s.setDirty);
  const selectedFilePath = useAppStore((s) => s.selectedFilePath);
  const setEditingFileMeta = useAppStore((s) => s.setEditingFileMeta);
  const queryClient = useQueryClient();

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef<boolean>(false);
  const reSendRef = useRef<boolean>(false);

  const flush = async (): Promise<void> => {
    const state = useAppStore.getState();
    const model = state.editingModel;
    if (!model) return;
    if (state.selectedFilePath === null) return;
    if (inFlightRef.current) {
      reSendRef.current = true;
      return;
    }
    inFlightRef.current = true;
    try {
      // ``expectedEtag`` は楽観ロック用 (= ADR-0041 §論点 11-A)。null なら単に
      // 上書きで OK。
      const resp = await putFileContent(
        state.selectedFilePath,
        model,
        state.editingFileEtag ?? undefined,
      );
      // 保存後の最新 etag / mtime を反映 (= 次回 PUT で楽観ロックが正しく動く)
      setEditingFileMeta(resp.mtime, resp.etag);
      setDirty(false);
      await queryClient.invalidateQueries({ queryKey: ["files-tree"] });
    } catch (e) {
      console.error("auto-save failed:", e);
      // dirty を維持 (ユーザーは編集継続できる)
    } finally {
      inFlightRef.current = false;
      if (reSendRef.current) {
        reSendRef.current = false;
        // 並走中の debounce タイマーが残っていたら無効化 (= 二重 PUT 防止、
        // ADR-0019 code-reviewer SHOULD 修正)
        if (timerRef.current) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        void flush();
      }
    }
  };

  // dirty 変化で debounce タイマー再設定
  useEffect(() => {
    if (!dirty || !editingModel) return;
    if (selectedFilePath === null) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      void flush();
    }, AUTO_SAVE_DEBOUNCE_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // flush は ref に閉じているので deps から省略
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, editingModel, selectedFilePath]);

  // Ctrl+S で即時 PUT
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        if (timerRef.current) clearTimeout(timerRef.current);
        void flush();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // beforeunload で dirty なら警告 + best-effort 即時 PUT
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent): string | undefined => {
      if (dirty) {
        e.preventDefault();
        // 即時 flush (best-effort、ブラウザは await できないが fire-and-forget)
        if (timerRef.current) clearTimeout(timerRef.current);
        void flush();
        e.returnValue = "Unsaved changes will be lost.";
        return e.returnValue;
      }
      return undefined;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty]);
}
