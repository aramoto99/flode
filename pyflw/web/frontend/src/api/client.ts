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

export async function deleteModel(modelId: string): Promise<void> {
  await _fetch(`/models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
}

/**
 * "Save As" / Rename: 現在の model を新しい id にコピーする。
 * サーバ側に専用 endpoint がないので 3 ステップ (read → write to new → optionally delete old)。
 *
 * @param oldId 元 model id
 * @param newId 新 model id
 * @param deleteOriginal true なら元ファイルを削除 (= rename)、false なら残す (= save-as)
 * @returns 新規作成された model id (server が衝突回避で suffix を付けた場合があるためそれを返す)
 */
export async function copyModel(
  oldId: string,
  newId: string,
  { deleteOriginal }: { deleteOriginal: boolean },
): Promise<string> {
  const data = await getModel(oldId);
  const payload: FlwModel = {
    ...data,
    metadata: { ...(data.metadata ?? {}), name: newId },
  };
  // POST で衝突回避 + 新規作成 (= 既存 file には書き込まない)
  const resp = await createModel(payload);
  if (deleteOriginal && resp.model_id !== oldId) {
    await deleteModel(oldId);
  }
  return resp.model_id;
}

/**
 * Untitled モデルの auto-name を計算する (現存 model 一覧と衝突しない最小の suffix)。
 * Simulink ``untitled1.slx`` 風 (アンダースコアなし)。
 */
export async function nextUntitledName(): Promise<string> {
  const list = await listModels();
  const taken = new Set(list.models);
  for (let i = 1; i < 10000; i++) {
    const candidate = `untitled${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  throw new Error("Cannot allocate untitled<N>: too many models");
}
