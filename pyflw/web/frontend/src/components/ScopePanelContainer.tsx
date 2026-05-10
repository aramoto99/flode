// ADR-0044 §論点 3 / §論点 6 / §論点 11: 全 Scope panel を最上位で管理する
// container コンポーネント。``store.scopePanels`` (= 開いている scope_id 配列) を
// subscribe し、各 scope_id に対して ``react-rnd`` で drag + resize 可能な
// floating panel を描画する。位置・サイズは localStorage に永続化。

import { useEffect } from "react";
import { Rnd } from "react-rnd";

import { useAppStore } from "../store/appStore";
import { ScopeView } from "./ScopeView";
import { XYGraphView } from "./XYGraphView";

interface PanelGeometry {
  x: number;
  y: number;
  w: number;
  h: number;
}

const DEFAULT_GEOMETRY: PanelGeometry = { x: 200, y: 200, w: 480, h: 320 };

function makeKey(workspaceHash: string, modelPath: string, scopeId: string): string {
  // ADR-0044 §論点 6-A: pyflw.scope_panel.<hash>.<base64url(model_path)>.<scope_id>
  const b64 = btoa(modelPath)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  return `pyflw.scope_panel.${workspaceHash}.${b64}.${scopeId}`;
}

function loadGeometry(key: string): PanelGeometry {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return { ...DEFAULT_GEOMETRY };
    const parsed = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof parsed.x === "number" &&
      typeof parsed.y === "number" &&
      typeof parsed.w === "number" &&
      typeof parsed.h === "number"
    ) {
      return parsed as PanelGeometry;
    }
  } catch {
    // 無視
  }
  return { ...DEFAULT_GEOMETRY };
}

function saveGeometry(key: string, g: PanelGeometry): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(g));
  } catch {
    // quota / private mode は黙って失敗
  }
}

export function ScopePanelContainer(): JSX.Element {
  const scopePanels = useAppStore((s) => s.scopePanels);
  const scopes = useAppStore((s) => s.scopes);
  const workspaceHash = useAppStore((s) => s.workspaceHash);
  const activeTabFilePath = useAppStore((s) => s.activeTabFilePath);
  const closeAllScopePanels = useAppStore((s) => s.closeAllScopePanels);
  const editingModel = useAppStore((s) => s.editingModel);

  // ADR-0044 §論点 11: モデル切替で全 panel を閉じる
  useEffect(() => {
    closeAllScopePanels();
  }, [activeTabFilePath, closeAllScopePanels]);

  if (scopePanels.length === 0) return <></>;

  return (
    <>
      {scopePanels.map((scopeId, idx) => {
        const buffer = scopes[scopeId];
        if (!buffer) return null;
        const blockType = (() => {
          if (!editingModel) return "";
          for (const b of editingModel.blocks) {
            if (b.id === scopeId) return b.type;
          }
          return "";
        })();
        // 永続化キー (= workspaceHash + activeTabFilePath が揃っている時のみ)
        const key =
          workspaceHash && activeTabFilePath
            ? makeKey(workspaceHash, activeTabFilePath, scopeId)
            : null;
        const initial = key
          ? loadGeometry(key)
          : { ...DEFAULT_GEOMETRY, x: DEFAULT_GEOMETRY.x + idx * 30, y: DEFAULT_GEOMETRY.y + idx * 30 };

        return (
          <Rnd
            key={scopeId}
            default={{
              x: initial.x,
              y: initial.y,
              width: initial.w,
              height: initial.h,
            }}
            minWidth={280}
            minHeight={180}
            bounds="window"
            dragHandleClassName="scope-panel-drag-handle"
            onDragStop={(_, d) => {
              if (!key) return;
              const cur = loadGeometry(key);
              saveGeometry(key, { ...cur, x: d.x, y: d.y });
            }}
            onResizeStop={(_, __, ref, ___, position) => {
              if (!key) return;
              saveGeometry(key, {
                x: position.x,
                y: position.y,
                w: ref.offsetWidth,
                h: ref.offsetHeight,
              });
            }}
            // ADR-0044 §論点 6: 後にクリックされた panel が前面 (= z-index 順)
            style={{ zIndex: 40 + idx, pointerEvents: "auto" }}
            className="rounded border border-slate-400 bg-white shadow-2xl"
          >
            <div className="flex h-full flex-col">
              <div className="scope-panel-drag-handle flex h-6 cursor-move items-center border-b border-slate-300 bg-slate-100 px-2 text-[11px] font-medium text-slate-700">
                <span className="font-mono">{scopeId}</span>
              </div>
              <div className="flex-1 overflow-hidden">
                {blockType.endsWith(".XYGraph") ? (
                  <XYGraphView scopeId={scopeId} buffer={buffer} />
                ) : (
                  <ScopeView
                    scopeId={scopeId}
                    buffer={buffer}
                    formFactor="panel"
                  />
                )}
              </div>
            </div>
          </Rnd>
        );
      })}
    </>
  );
}
