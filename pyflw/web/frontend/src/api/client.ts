// REST API クライアント (ADR-0011 §(1)、ADR-0019 §(1)、ADR-0029、ADR-0041 §5)。
//
// v0.21.0: legacy ``/api/v1/models/*`` 系 (= listModels / getModel / updateModel /
// createModel / deleteModel / copyModel / nextUntitledName / startSimulation の
// model_id body 経路) を全削除。File API (= filesApi.ts) と
// startSimulationByPath / startSimulationInline のみが残る。
import type {
  BlockMetadata,
  BlockRegistryResponse,
  FlwModel,
  LibraryEntryDetail,
  LibraryRegistryResponse,
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

/**
 * ADR-0041 §論点 5-A: workspace 相対 path でシミュレーション開始。
 * backend が `resolve_workspace_path` で path traversal 防御を通したのち、
 * `Simulator.load(path)` で構築する。
 */
export async function startSimulationByPath(
  modelPath: string,
): Promise<{ simulation_id: string; model_id: string }> {
  return _fetch("/simulations", {
    method: "POST",
    body: JSON.stringify({ model_path: modelPath }),
  });
}

/**
 * ADR-0041 §論点 5-A: インラインモデルでシミュレーション開始 (= 未保存
 * editingModel の試行実行)。本関数は **保存をスキップ**して in-memory dict を
 * そのまま渡すため、ファイル化されていないモデルを試走するときに使う。
 */
export async function startSimulationInline(
  model: FlwModel,
): Promise<{ simulation_id: string; model_id: string }> {
  return _fetch("/simulations", {
    method: "POST",
    body: JSON.stringify({ model }),
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

// ADR-0029: Library file format endpoints。
// list は subsystem body を含めない (= ペイロード削減、palette 表示用)。drop 時に
// 個別 entry を fetch して inline 展開する。
export async function listLibraries(): Promise<LibraryRegistryResponse> {
  return _fetch<LibraryRegistryResponse>("/libraries");
}

export async function getLibraryEntry(
  libraryName: string,
  entryId: string,
): Promise<LibraryEntryDetail> {
  return _fetch<LibraryEntryDetail>(
    `/libraries/${encodeURIComponent(libraryName)}/${encodeURIComponent(entryId)}`,
  );
}
