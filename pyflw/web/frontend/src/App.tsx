import { ReactFlowProvider } from "@xyflow/react";
import { useState } from "react";

import { BlockPalette } from "./components/BlockPalette";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { ModelList } from "./components/ModelList";
import { ParameterPanel } from "./components/ParameterPanel";
import { ScopeView } from "./components/ScopeView";
import { SimulationControls } from "./components/SimulationControls";
import { useAutoSave } from "./lib/useAutoSave";
import { useAppStore } from "./store/appStore";

type SidebarTab = "models" | "palette";

export default function App(): JSX.Element {
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const dirty = useAppStore((s) => s.dirty);
  const scopes = useAppStore((s) => s.scopes);
  const [sidebarTab, setSidebarTab] = useState<SidebarTab>("models");

  // ADR-0019 §(5): debounce auto-save / Ctrl+S / beforeunload
  useAutoSave();

  return (
    <ReactFlowProvider>
      <div className="grid h-full grid-cols-[260px_1fr_280px] grid-rows-[auto_1fr] bg-gray-50 text-gray-900">
        <header className="col-span-3 flex items-center border-b border-gray-200 bg-white px-4 py-2">
          <h1 className="text-lg font-semibold">pyflw</h1>
          <span className="ml-3 text-xs text-gray-500">v{__APP_VERSION__}</span>
          {selectedModelId && (
            <span className="ml-4 text-xs text-gray-700">
              {selectedModelId}
              {dirty && (
                <span
                  className="ml-1 text-amber-600"
                  title="Unsaved changes"
                  aria-label="Unsaved changes"
                >
                  *
                </span>
              )}
            </span>
          )}
        </header>
        <aside className="row-start-2 flex flex-col border-r border-gray-200 bg-white">
          <div className="flex border-b border-gray-200">
            <button
              type="button"
              className={`flex-1 px-2 py-1.5 text-xs font-medium ${
                sidebarTab === "models"
                  ? "border-b-2 border-blue-500 text-blue-700"
                  : "text-gray-500 hover:text-gray-700"
              }`}
              onClick={() => setSidebarTab("models")}
            >
              Models
            </button>
            <button
              type="button"
              className={`flex-1 px-2 py-1.5 text-xs font-medium ${
                sidebarTab === "palette"
                  ? "border-b-2 border-blue-500 text-blue-700"
                  : "text-gray-500 hover:text-gray-700"
              }`}
              onClick={() => setSidebarTab("palette")}
            >
              Palette
            </button>
          </div>
          <div className="flex-1 overflow-hidden">
            {sidebarTab === "models" ? <ModelList /> : <BlockPalette />}
          </div>
        </aside>
        <main className="row-start-2 flex flex-col">
          {selectedModelId ? (
            <>
              <div className="flex-1 border-b border-gray-200">
                <DiagramCanvas modelId={selectedModelId} />
              </div>
              <SimulationControls modelId={selectedModelId} />
              <div className="flex flex-col gap-2 overflow-y-auto p-3">
                {Object.entries(scopes).length === 0 ? (
                  <div className="text-xs text-gray-500">
                    Run a simulation to see scope data.
                  </div>
                ) : (
                  Object.entries(scopes).map(([scopeId, buffer]) => (
                    <ScopeView key={scopeId} scopeId={scopeId} buffer={buffer} />
                  ))
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-gray-500">
              Select a model from the left panel to view its diagram.
            </div>
          )}
        </main>
        <aside className="row-start-2 overflow-y-auto">
          {selectedModelId ? (
            <ParameterPanel modelId={selectedModelId} />
          ) : (
            <div className="border-l border-gray-200 bg-white p-3 text-xs text-gray-500">
              (parameter panel)
            </div>
          )}
        </aside>
      </div>
    </ReactFlowProvider>
  );
}
