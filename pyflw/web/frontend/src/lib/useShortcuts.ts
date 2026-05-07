// Simulink ライクなキーボードショートカットを App ルートで束ねる hook。
// 入力フォーカス中 (input / textarea / contenteditable) はテキスト編集を優先する
// (= Ctrl+A はテキスト全選択、Ctrl+C はテキストコピーが OS / ブラウザ動作)。

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { listBlockMetadata } from "../api/client";
import {
  copySelectionToClipboard,
  pasteClipboard,
  selectAllInScope,
  useAppStore,
} from "../store/appStore";
import { resolveBlocksAtPath } from "./pathResolver";
import { useSimulation } from "./useSimulation";

/** focus が text 編集要素にあるとき true。テキスト系の Ctrl+A/C/V はブラウザ任せ。 */
function isTextEditing(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  return false;
}

export function useShortcuts(): void {
  const { run, stop } = useSimulation();
  const { data: registry } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });

  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key;

      // ---- Run / Stop ----
      // Simulink は Ctrl+T = Run / Ctrl+Shift+T = Stop。ただしほとんどのブラウザは
      // Ctrl+T (= 新しいタブ) と Ctrl+Shift+T (= 閉じたタブを復元) を OS レベルで
      // 横取りし preventDefault を無視する。デスクトップアプリ化 (PWA / Electron 等)
      // した場合に備えて bind は残しつつ、確実に動く F9 / Shift+F9 もエイリアスする
      // (= 多くの IDE で慣習)。
      if (
        (ctrl && !e.shiftKey && key.toLowerCase() === "t") ||
        (!ctrl && !e.shiftKey && key === "F9")
      ) {
        e.preventDefault();
        void run();
        return;
      }
      if (
        (ctrl && e.shiftKey && key.toLowerCase() === "t") ||
        (!ctrl && e.shiftKey && key === "F9")
      ) {
        e.preventDefault();
        void stop();
        return;
      }

      // ---- 以下、テキスト編集中はブラウザ動作を優先 ----
      if (isTextEditing(e.target)) return;

      // Ctrl+A 全選択
      if (ctrl && !e.shiftKey && key.toLowerCase() === "a") {
        e.preventDefault();
        selectAllInScope();
        return;
      }
      // Ctrl+C コピー
      if (ctrl && !e.shiftKey && key.toLowerCase() === "c") {
        e.preventDefault();
        copySelectionToClipboard();
        return;
      }
      // Ctrl+V 貼り付け
      if (ctrl && !e.shiftKey && key.toLowerCase() === "v") {
        e.preventDefault();
        pasteClipboard();
        return;
      }

      // Esc: 階層を上に / 選択解除
      // Subsystem の中にいるなら drillUp、それ以外は選択解除。Simulink でも
      // Esc は段階的に「外向き」のキャンセル動作。
      if (key === "Escape") {
        const state = useAppStore.getState();
        if (state.editingPath.length > 0) {
          state.drillUp();
        } else if (
          state.selectedNodeIds.length > 0 ||
          state.selectedEdgeIds.length > 0
        ) {
          state.selectNode(null);
          state.setSelectedEdgeIds([]);
        }
        return;
      }

      // Enter: 単一選択された Subsystem (= is_container) に潜る
      if (key === "Enter") {
        const state = useAppStore.getState();
        if (state.selectedNodeIds.length !== 1) return;
        const blockId = state.selectedNodeIds[0]!;
        const model = state.editingModel;
        if (!model || !registry) return;
        let view;
        try {
          view = resolveBlocksAtPath(model, state.editingPath);
        } catch {
          return;
        }
        const block = view.blocks.find((b) => b.id === blockId);
        if (!block) return;
        const meta = registry.blocks.find((m) => m.type_path === block.type);
        if (!meta?.is_container) return;
        e.preventDefault();
        state.drilldownInto(blockId);
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [run, stop, registry]);
}
