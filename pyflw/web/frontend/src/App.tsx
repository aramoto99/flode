import { ModelList } from "./components/ModelList";
import { DiagramCanvas } from "./components/DiagramCanvas";
import { SimulationControls } from "./components/SimulationControls";
import { ScopeView } from "./components/ScopeView";
import { useAppStore } from "./store/appStore";

export default function App(): JSX.Element {
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const scopes = useAppStore((s) => s.scopes);

  return (
    <div className="grid h-full grid-cols-[260px_1fr] grid-rows-[auto_1fr] bg-gray-50 text-gray-900">
      <header className="col-span-2 flex items-center border-b border-gray-200 bg-white px-4 py-2">
        <h1 className="text-lg font-semibold">pyflw</h1>
        <span className="ml-3 text-xs text-gray-500">v0.2.0-dev0</span>
      </header>
      <aside className="row-start-2 border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-3">
          <h2 className="text-sm font-medium">Models</h2>
        </div>
        <ModelList />
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
    </div>
  );
}
