// ADR-0019 §(7): Create New Model ボタンを追加し、空 layout 0.5 モデルを POST で作る。

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { createModel, listModels } from "../api/client";
import type { FlwModel } from "../types/api";
import { useAppStore } from "../store/appStore";

function emptyModel(name: string): FlwModel {
  return {
    schema_version: "0.5",
    metadata: { name, tool: "pyflw GUI" },
    simulator: {
      t_end: 10.0,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

export function ModelList(): JSX.Element {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: listModels,
  });
  const queryClient = useQueryClient();
  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectModel = useAppStore((s) => s.selectModel);
  const [newName, setNewName] = useState("");

  const createMutation = useMutation({
    mutationFn: (name: string) => createModel(emptyModel(name || "model")),
    onSuccess: async (resp) => {
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      selectModel(resp.model_id);
      setNewName("");
    },
  });

  const handleCreate = (): void => {
    if (createMutation.isPending) return;
    createMutation.mutate(newName.trim());
  };

  if (isLoading) {
    return <div className="p-2 text-sm text-gray-500">Loading...</div>;
  }
  if (error) {
    return (
      <div className="p-2 text-sm text-red-600">
        Failed to load: {(error as Error).message}
      </div>
    );
  }
  const models = data?.models ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-col gap-1 border-b border-gray-200 p-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New model name..."
          onKeyDown={(e) => {
            if (e.key === "Enter") handleCreate();
          }}
          className="w-full rounded border border-gray-300 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
          aria-label="New model name"
        />
        <button
          type="button"
          onClick={handleCreate}
          disabled={createMutation.isPending}
          className="rounded bg-blue-600 px-2 py-1 text-xs text-white hover:bg-blue-700 disabled:bg-gray-400"
        >
          {createMutation.isPending ? "Creating..." : "+ New Model"}
        </button>
        {createMutation.error && (
          <span className="text-[10px] text-red-600">
            {(createMutation.error as Error).message}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto">
        {models.length === 0 ? (
          <div className="p-2 text-sm text-gray-500">No models</div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {models.map((m) => (
              <li key={m}>
                <button
                  type="button"
                  onClick={() => selectModel(m)}
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-gray-100 ${
                    selectedModelId === m ? "bg-blue-50 font-medium" : ""
                  }`}
                >
                  {m}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
