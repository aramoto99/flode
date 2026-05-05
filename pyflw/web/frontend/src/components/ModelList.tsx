import { useQuery } from "@tanstack/react-query";

import { listModels } from "../api/client";
import { useAppStore } from "../store/appStore";

export function ModelList(): JSX.Element {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: listModels,
  });

  const selectedModelId = useAppStore((s) => s.selectedModelId);
  const selectModel = useAppStore((s) => s.selectModel);

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
  if (models.length === 0) {
    return <div className="p-2 text-sm text-gray-500">No models</div>;
  }
  return (
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
  );
}
