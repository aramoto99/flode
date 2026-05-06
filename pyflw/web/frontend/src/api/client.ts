// REST API クライアント (ADR-0011 §(1)、ADR-0019 §(1))。
import type {
  BlockMetadata,
  BlockRegistryResponse,
  FlwModel,
  ModelList,
  ResolvedPortShapes,
  SimulationState,
} from "../types/api";

const API_BASE = "/api/v1";

async function _fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail: string;
    try {
      const body = await response.json();
      detail =
        body?.error?.message ?? body?.detail ?? response.statusText;
    } catch {
      detail = response.statusText;
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

export async function listModels(): Promise<ModelList> {
  return _fetch<ModelList>("/models");
}

export async function getModel(modelId: string): Promise<FlwModel> {
  return _fetch<FlwModel>(`/models/${encodeURIComponent(modelId)}`);
}

export async function updateModel(
  modelId: string,
  payload: FlwModel,
): Promise<{ model_id: string }> {
  return _fetch(`/models/${encodeURIComponent(modelId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function startSimulation(
  modelId: string,
): Promise<{ simulation_id: string; model_id: string }> {
  return _fetch("/simulations", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId }),
  });
}

export async function stopSimulation(simId: string): Promise<void> {
  await _fetch(`/simulations/${encodeURIComponent(simId)}/stop`, {
    method: "POST",
  });
}

export async function getSimulationState(
  simId: string,
): Promise<SimulationState> {
  return _fetch<SimulationState>(
    `/simulations/${encodeURIComponent(simId)}`,
  );
}

// ADR-0019 §(1): Block class registry endpoints
export async function listBlockMetadata(): Promise<BlockRegistryResponse> {
  return _fetch<BlockRegistryResponse>("/blocks");
}

// Phase 4 (ADR-0021 マスクパラメータ UI / ParameterPanel 拡張) で利用予定。
// Phase 3 では palette 表示には list endpoint で十分。
export async function getBlockMetadata(typePath: string): Promise<BlockMetadata> {
  return _fetch<BlockMetadata>(`/blocks/${encodeURIComponent(typePath)}`);
}

export async function resolvePortShapes(
  typePath: string,
  params: Record<string, unknown>,
): Promise<ResolvedPortShapes> {
  return _fetch<ResolvedPortShapes>("/blocks/resolve-port-shapes", {
    method: "POST",
    body: JSON.stringify({ type_path: typePath, params }),
  });
}

// ADR-0019 §(7): Create new model
export async function createModel(
  payload: FlwModel,
): Promise<{ model_id: string }> {
  return _fetch("/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// Phase 4 (削除 UI / multi-select 削除) で利用予定。endpoint 自体は ADR-0011 で定義済み。
export async function deleteModel(modelId: string): Promise<void> {
  await _fetch(`/models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
}
