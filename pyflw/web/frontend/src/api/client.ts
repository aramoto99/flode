// REST API クライアント (ADR-0011 §(1))。
import type {
  FlwModel,
  ModelList,
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
