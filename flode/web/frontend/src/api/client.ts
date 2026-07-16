// REST API クライアント (ADR-0011 §(1)、ADR-0019 §(1)、ADR-0029、ADR-0041 §5)。
//
// v0.21.0: legacy ``/api/v1/models/*`` 系 (= listModels / getModel / updateModel /
// createModel / deleteModel / copyModel / nextUntitledName / startSimulation の
// model_id body 経路) を全削除。File API (= filesApi.ts) と
// startSimulationByPath / startSimulationInline のみが残る。
import type {
  BlockMetadata,
  BlockRegistryResponse,
  FailurePayload,
  FlwModel,
  LibraryEntryDetail,
  LibraryRegistryResponse,
  ResolvedPortShapes,
  SimulationResults,
  SimulationState,
} from "../types/api";

const API_BASE = "/api/v1";

/** ADR-0056 §B-2: REST start API は失敗時に構造化 detail (``FailurePayload``)
 *  を ``{detail: {...}}`` で返す。``ApiError`` はその detail を呼出側に届ける
 *  ための custom Error。``message`` には人間可読な文字列が入り、``structured``
 *  には FailurePayload を持つ (= 構造化 detail でなければ ``null``)。 */
export class ApiError extends Error {
  readonly status: number;
  readonly structured: FailurePayload | null;
  readonly rawDetail: unknown;
  constructor(
    status: number,
    message: string,
    structured: FailurePayload | null,
    rawDetail: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.structured = structured;
    this.rawDetail = rawDetail;
  }
}

function _structuredOrNull(detail: unknown): FailurePayload | null {
  // ADR-0056 §B-2: 構造化 detail の最低条件 = ``category`` + ``template_key`` +
  // ``raw_message`` がすべて string であること。code-reviewer MUST-3: FastAPI の
  // 標準 validation エラー等が偶然 ``category`` を含む dict を返した場合に誤って
  // FailurePayload にアサートしないよう、必須 3 field 全てを isString チェック。
  if (
    typeof detail === "object" &&
    detail !== null &&
    typeof (detail as { category?: unknown }).category === "string" &&
    typeof (detail as { template_key?: unknown }).template_key === "string" &&
    typeof (detail as { raw_message?: unknown }).raw_message === "string"
  ) {
    return detail as FailurePayload;
  }
  return null;
}

async function _fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      // body 無し or non-JSON は OK
    }
    const body = parsed as
      | { error?: { message?: string }; detail?: unknown }
      | null;
    const rawDetail = body?.detail ?? body?.error ?? null;
    const structured = _structuredOrNull(rawDetail);
    const message: string =
      structured?.raw_message
      ?? (typeof body?.detail === "string" ? body.detail : undefined)
      ?? body?.error?.message
      ?? response.statusText;
    throw new ApiError(response.status, `${response.status} ${message}`, structured, rawDetail);
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

/**
 * 終端後に完全な Scope データを一括取得する (ADR-0011 §(1))。
 * WS ストリームの queue 満杯 drop で欠損しうる波形を、この結果で置き換える。
 * 実行中は 409 (SimulationStillRunningError) が返る。
 */
export async function getSimulationResults(
  simId: string,
): Promise<SimulationResults> {
  return _fetch<SimulationResults>(
    `/simulations/${encodeURIComponent(simId)}/results`,
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
