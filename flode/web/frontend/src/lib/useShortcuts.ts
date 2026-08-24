// リファレンスツール風のキーボードショートカットを App ルートで束ねる hook。
// 入力フォーカス中 (input / textarea / contenteditable) はテキスト編集を優先する
// (= Ctrl+A はテキスト全選択、Ctrl+C はテキストコピーが OS / ブラウザ動作)。

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { listBlockMetadata } from "../api/client";
import {
  copySelectionToClipboard,
  pasteClipboard,
  removeBlockFromEditing,
  selectAllInScope,
  toggleBlockFlipped,
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
  // ADR-0052 §(6): Ctrl+K 2-stroke prefix の active 状態 (= 1.5 秒 timeout)
  const ctrlKPrefixActiveRef = useRef(false);
  const ctrlKPrefixTimeoutRef = useRef<number | null>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      const ctrl = e.ctrlKey || e.metaKey;
      const key = e.key;

      // ---- Run / Stop ----
      // リファレンスツールは Ctrl+T = Run / Ctrl+Shift+T = Stop。ただしほとんどのブラウザは
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

      // v0.20.0: Ctrl+Z Undo / Ctrl+Shift+Z (= Ctrl+Y) Redo
      // リファレンスツール / VS Code 流儀。Mac は Cmd+Z / Cmd+Shift+Z (= ctrl 変数で吸収)。
      if (ctrl && !e.shiftKey && key.toLowerCase() === "z") {
        e.preventDefault();
        useAppStore.getState().undo();
        return;
      }
      if (
        (ctrl && e.shiftKey && key.toLowerCase() === "z") ||
        (ctrl && !e.shiftKey && key.toLowerCase() === "y")
      ) {
        e.preventDefault();
        useAppStore.getState().redo();
        return;
      }

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
      // Ctrl+X カット (= Copy + 削除)
      if (ctrl && !e.shiftKey && key.toLowerCase() === "x") {
        e.preventDefault();
        copySelectionToClipboard();
        // 選択中の block を削除 (= addBlockToEditing と対称な removeBlockFromEditing)
        const state = useAppStore.getState();
        for (const id of state.selectedNodeIds) {
          // import 循環を避けるため動的 require ではなく直接 state action を使う
          // — removeBlockFromEditing は appStore.ts の export だが本 file は
          // top-level で import している
          removeBlockFromEditing(id);
        }
        state.selectNode(null);
        return;
      }
      // Ctrl+V 貼り付け
      if (ctrl && !e.shiftKey && key.toLowerCase() === "v") {
        e.preventDefault();
        pasteClipboard();
        return;
      }

      // ADR-0043 §論点 2: Ctrl+Tab / Ctrl+Shift+Tab でタブ切替 (VSCode 流儀)。
      // Ctrl+Tab はブラウザのタブ切替に取られるが、preventDefault で握り潰せる
      // (= focus がページ内ならブラウザ shortcut より event listener が先)。
      if (ctrl && key === "Tab") {
        e.preventDefault();
        const state = useAppStore.getState();
        if (state.tabs.length < 2) return;
        const currentIdx = state.tabs.findIndex(
          (t) => t.filePath === state.activeTabFilePath,
        );
        if (currentIdx < 0) return;
        const delta = e.shiftKey ? -1 : 1;
        const nextIdx =
          (currentIdx + delta + state.tabs.length) % state.tabs.length;
        const nextTab = state.tabs[nextIdx];
        if (nextTab) state.switchTab(nextTab.filePath);
        return;
      }

      // ADR-0043 §論点 5-A → ADR-0051 §(2-A): Ctrl+P (path 検索) /
      // Ctrl+Shift+F (内容検索) の semantics 変更。
      // 旧: overlay を開く
      // 新: activity bar sidebar mode を ``search`` に切替 + sidebar 展開 +
      //     kind を SearchPanel に伝達 (= ``flode:open-search`` event は維持、
      //     SearchPanel が kind を受けて state 更新 + input focus)
      if (ctrl && !e.shiftKey && key.toLowerCase() === "p") {
        e.preventDefault();
        const state = useAppStore.getState();
        state.setSidebarMode("search");
        if (state.workspaceCollapsed) state.setWorkspaceCollapsed(false);
        window.dispatchEvent(
          new CustomEvent("flode:open-search", { detail: { kind: "path" } }),
        );
        return;
      }
      if (ctrl && e.shiftKey && key.toLowerCase() === "f") {
        e.preventDefault();
        const state = useAppStore.getState();
        state.setSidebarMode("search");
        if (state.workspaceCollapsed) state.setWorkspaceCollapsed(false);
        window.dispatchEvent(
          new CustomEvent("flode:open-search", { detail: { kind: "content" } }),
        );
        return;
      }

      // ADR-0051 §(7): Ctrl+B = sidebar 全体 toggle (= VSCode 流)
      if (ctrl && !e.shiftKey && key.toLowerCase() === "b") {
        e.preventDefault();
        const state = useAppStore.getState();
        state.setWorkspaceCollapsed(!state.workspaceCollapsed);
        return;
      }

      // ADR-0051 §(7): Ctrl+Shift+E = sidebar mode を file に切替 + open
      if (ctrl && e.shiftKey && key.toLowerCase() === "e") {
        e.preventDefault();
        const state = useAppStore.getState();
        state.setSidebarMode("file");
        if (state.workspaceCollapsed) state.setWorkspaceCollapsed(false);
        return;
      }

      // v0.29.0: Ctrl+Shift+P = コマンドパレットを open (= 一般的な Web IDE 流)
      if (ctrl && e.shiftKey && key.toLowerCase() === "p") {
        e.preventDefault();
        useAppStore.getState().setCommandPaletteOpen(true);
        return;
      }

      // ADR-0052 §(6) Stage 3: Ctrl+\ = active tab を右に split (= drag-to-
      // split-tab の代替キーボード操作)。activeTabFilePath を tab:<filePath>
      // 葉として diagram pane の右に horizontal split で追加。
      if (ctrl && !e.shiftKey && key === "\\") {
        e.preventDefault();
        const state = useAppStore.getState();
        const path = state.activeTabFilePath;
        if (!path) return;
        const tabLeafId = `tab:${path}`;
        // 既に SplitTree 内に存在するなら no-op
        const layout = state.workspaceLayout;
        const leaves = new Set<string>();
        const collect = (t: typeof layout): void => {
          if (t.kind === "leaf") leaves.add(t.paneId);
          else {
            collect(t.a);
            collect(t.b);
          }
        };
        collect(layout);
        if (leaves.has(tabLeafId)) return;
        state.splitPane("diagram", "horizontal", tabLeafId, "after");
        return;
      }

      // ADR-0052 §(6) Stage 3: Ctrl+K prefix の 2-stroke shortcut。
      // K を押した後 次の keydown を待ち、I = Inspector mode cycle / Z = Zen mode
      // (= sidebar 折りたたみ + Inspector sidebar 折りたたみ) を発火。
      // prefix mode は 1.5 秒で timeout (= 利用者が他キーを押す前に解除)。
      if (ctrl && !e.shiftKey && key.toLowerCase() === "k") {
        e.preventDefault();
        ctrlKPrefixActiveRef.current = true;
        if (ctrlKPrefixTimeoutRef.current !== null) {
          window.clearTimeout(ctrlKPrefixTimeoutRef.current);
        }
        ctrlKPrefixTimeoutRef.current = window.setTimeout(() => {
          ctrlKPrefixActiveRef.current = false;
        }, 1500);
        return;
      }
      if (ctrlKPrefixActiveRef.current) {
        const k = key.toLowerCase();
        if (k === "i") {
          e.preventDefault();
          ctrlKPrefixActiveRef.current = false;
          if (ctrlKPrefixTimeoutRef.current !== null) {
            window.clearTimeout(ctrlKPrefixTimeoutRef.current);
            ctrlKPrefixTimeoutRef.current = null;
          }
          // Inspector mode cycle: sidebar → pane → float → sidebar
          const s = useAppStore.getState();
          const next: "sidebar" | "pane" | "float" =
            s.inspectorDockMode === "sidebar"
              ? "pane"
              : s.inspectorDockMode === "pane"
                ? "float"
                : "sidebar";
          s.setInspectorDockMode(next);
          return;
        }
        if (k === "z") {
          e.preventDefault();
          ctrlKPrefixActiveRef.current = false;
          if (ctrlKPrefixTimeoutRef.current !== null) {
            window.clearTimeout(ctrlKPrefixTimeoutRef.current);
            ctrlKPrefixTimeoutRef.current = null;
          }
          // Zen mode toggle: sidebar + inspector の両方を折りたたむ / 戻す
          const s = useAppStore.getState();
          const isZen = s.workspaceCollapsed && s.inspectorCollapsed;
          s.setWorkspaceCollapsed(!isZen);
          s.setInspectorCollapsed(!isZen);
          return;
        }
        if (key === "\\" && ctrl) {
          // Ctrl+K Ctrl+\ = split down (= 上下分割で tab leaf 追加)
          e.preventDefault();
          ctrlKPrefixActiveRef.current = false;
          if (ctrlKPrefixTimeoutRef.current !== null) {
            window.clearTimeout(ctrlKPrefixTimeoutRef.current);
            ctrlKPrefixTimeoutRef.current = null;
          }
          const s = useAppStore.getState();
          const path = s.activeTabFilePath;
          if (!path) return;
          s.splitPane("diagram", "vertical", `tab:${path}`, "after");
          return;
        }
        // Prefix mode 中の他キー = prefix 解除のみ
        ctrlKPrefixActiveRef.current = false;
        if (ctrlKPrefixTimeoutRef.current !== null) {
          window.clearTimeout(ctrlKPrefixTimeoutRef.current);
          ctrlKPrefixTimeoutRef.current = null;
        }
      }

      // v0.35.5: Ctrl+I = 選択ブロックを左右反転 (リファレンスツールの "Flip Block" 互換)。
      // Ctrl+K プレフィクス中の Ctrl+I (= Inspector dock cycle) は上で処理済、
      // ここに到達するのは通常 (= プレフィクス無し) の Ctrl+I のみ。
      if (ctrl && !e.shiftKey && key.toLowerCase() === "i") {
        const state = useAppStore.getState();
        const ids = state.selectedNodeIds;
        if (ids.length > 0) {
          e.preventDefault();
          for (const id of ids) {
            toggleBlockFlipped(id);
          }
        }
        return;
      }

      // F2: 単一選択ブロックの rename (SPEC-0022 §機能要件 1-3)。
      // BlockNodeView の BlockIdLabel が renameRequest を検知して inline 編集に入る。
      if (key === "F2") {
        const state = useAppStore.getState();
        if (state.selectedNodeIds.length === 1) {
          e.preventDefault();
          state.requestRename(state.selectedNodeIds[0]!);
        }
        return;
      }

      // Esc: 階層を上に / 選択解除
      // Subsystem の中にいるなら drillUp、それ以外は選択解除。リファレンスツールでも
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
    return () => {
      window.removeEventListener("keydown", handler);
      // ADR-0052 §(6) code-reviewer §SHOULD #1: unmount 時に Ctrl+K prefix
      // timeout が残留すると、unmount 後の callback で ref を書き換える
      // 可能性 (= HMR 等の頻繁 remount で症状顕在化) があるため明示的に clear。
      if (ctrlKPrefixTimeoutRef.current !== null) {
        window.clearTimeout(ctrlKPrefixTimeoutRef.current);
        ctrlKPrefixTimeoutRef.current = null;
      }
    };
  }, [run, stop, registry]);
}
