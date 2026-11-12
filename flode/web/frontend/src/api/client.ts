// REST API クライアント (ADR-0011 §(1)、ADR-0019 §(1)、ADR-0029、ADR-0041 §5)。
//
// v0.21.0: legacy ``/api/v1/models/*`` 系 (= listModels / getModel / updateModel /
// createModel / deleteModel / copyModel / nextUntitledName / startSimulation の
// model_id body 経路) を全削除。File API (= filesApi.ts) と
// startSimulationByPath / startSimulationInline のみが残る。
import type {
  BlockMetadata,
  BlockRegistryResponse,
  DtypesResponse,
  FailurePayload,
  FlwModel,
  LibraryEntryDetail,
  LibraryEntryMetadataPatch,
  LibraryImportReport,
  LibraryRegistryResponse,
  PythonFunctionIntrospectResponse,
  PythonFunctionParamEdit,
  PythonFunctionRewriteResponse,
  RegisterLibraryEntryRequest,
  ResolvedPortShapes,
  SimulationResults,
  SimulationState,
  UserLibraryEntryResponse,
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

/** ``fetch`` して、失敗 (non-2xx) なら ``ApiError`` を投げる。成功時は Response を返す。 */
async function _fetchResponse(path: string, init?: RequestInit): Promise<Response> {
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
  return response;
}

async function _fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await _fetchResponse(path, init);
  return response.json() as Promise<T>;
}

/**
 * ADR-0041 §論点 5-A: workspace 相対 path でシミュレーション開始。
 * backend が `resolve_workspace_path` で path traversal 防御を通したのち、
 * `Simulator.load(path)` で構築する。
 */
export async function startSimulationByPath(
  modelPath: string,
  pythonAck?: string,
): Promise<{ simulation_id: string; model_id: string }> {
  // SPEC-0023 soft gate: PythonFunction を含むモデルはサーバ計算 digest の echo
  // (``python_ack``) が無いと 409 (category ``python_function_unconfirmed``)。
  // 含まないモデルではサーバが無視する。
  const body: Record<string, unknown> = { model_path: modelPath };
  if (pythonAck !== undefined) body.python_ack = pythonAck;
  return _fetch("/simulations", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * SPEC-0023 / ADR-0073 §論点 1: PythonFunction ソースの静的解析。
 * サーバは exec しない (公開 bind でも安全)。``key`` はクライアント側の突合キー。
 */
export async function introspectPythonFunctions(
  items: ReadonlyArray<{ key: string; code: string }>,
): Promise<PythonFunctionIntrospectResponse> {
  return _fetch<PythonFunctionIntrospectResponse>(
    "/blocks/python-function/introspect",
    { method: "POST", body: JSON.stringify({ items }) },
  );
}

/**
 * SPEC-0024 §3.1: PythonFunction ソースのポート構造書き換え (サーバ側 AST splice)。
 * patch セマンティクス: 省略した key は書き換えない。サーバは exec しない。
 */
export async function rewritePythonFunction(
  code: string,
  edits: {
    inputs?: number;
    outputs?: number;
    input_names?: string[];
    output_names?: string[];
    /** SPEC-0025: パラメータ編集 (要素数 1 固定。rename はポート編集と併用不可)。 */
    params?: PythonFunctionParamEdit[];
  },
): Promise<PythonFunctionRewriteResponse> {
  return _fetch<PythonFunctionRewriteResponse>("/blocks/python-function/rewrite", {
    method: "POST",
    body: JSON.stringify({ code, edits }),
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

/**
 * SPEC-0027 (SM-D Stage 0): モデル全体の影の型解決。
 *
 * 表示専用の静的解析で、シミュレーションは実行されない (ユーザーコードも
 * 実行されない)。frontend では dtype を再計算せず本レスポンスの表示のみ行う
 * (ADR-0077 §データ整合性 1 の SSOT 制約)。
 *
 * @param model インライン model (= editingModel、未保存でよい)
 * @param signal debounce 中の旧リクエスト破棄用 AbortSignal
 */
export async function resolveModelDtypes(
  model: FlwModel,
  signal?: AbortSignal,
): Promise<DtypesResponse> {
  return _fetch<DtypesResponse>("/models/resolve-dtypes", {
    method: "POST",
    body: JSON.stringify({ model }),
    signal,
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

// ---------------------------------------------------------------------------
// ADR-0080: ライブラリ書き込み API。失敗時は ``ApiError.structured`` に
// ``{category: "library", template_key: "error.library.<code>", template_args}`` が
// 入る (表示文言への変換は lib/libraryErrors.ts)。
// ---------------------------------------------------------------------------

const USER_ENTRIES_PATH = "/libraries/user/entries";

/** ブロックをユーザーライブラリ (マイブロック) に登録する (新規 / 上書き / 別名保存)。 */
export async function registerLibraryEntry(
  request: RegisterLibraryEntryRequest,
): Promise<UserLibraryEntryResponse> {
  return _fetch<UserLibraryEntryResponse>(USER_ENTRIES_PATH, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** ユーザーライブラリのエントリの表示名・説明・分類を編集する (revision は上がらない)。 */
export async function updateLibraryEntryMetadata(
  entryId: string,
  patch: LibraryEntryMetadataPatch,
): Promise<UserLibraryEntryResponse> {
  return _fetch<UserLibraryEntryResponse>(
    `${USER_ENTRIES_PATH}/${encodeURIComponent(entryId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

/** ユーザーライブラリのエントリを削除する (``expectedRevision`` 不一致は 409)。 */
export async function deleteLibraryEntry(
  entryId: string,
  expectedRevision: number,
): Promise<void> {
  await _fetch(
    `${USER_ENTRIES_PATH}/${encodeURIComponent(entryId)}?expected_revision=${expectedRevision}`,
    { method: "DELETE" },
  );
}

/**
 * ライブラリファイルを取り込む。``content`` はファイル本文の文字列 (multipart は使えない)。
 * ``dryRun`` が真なら何も書き込まず検証結果だけ返る。``filename`` は表示専用。
 */
export async function importLibrary(
  content: string,
  options: { dryRun: boolean; filename?: string },
): Promise<LibraryImportReport> {
  return _fetch<LibraryImportReport>("/libraries/import", {
    method: "POST",
    body: JSON.stringify({
      content,
      dry_run: options.dryRun,
      ...(options.filename !== undefined ? { filename: options.filename } : {}),
    }),
  });
}

/** 取り込みライブラリを削除する (``origin === "imported"`` のみ)。 */
export async function deleteImportedLibrary(libraryName: string): Promise<void> {
  await _fetch(`/libraries/${encodeURIComponent(libraryName)}`, {
    method: "DELETE",
  });
}

/** 全ライブラリをディスクから読み直す (手で置いたファイルの反映)。 */
export async function reloadLibraries(): Promise<LibraryRegistryResponse> {
  return _fetch<LibraryRegistryResponse>("/libraries/reload", { method: "POST" });
}

/** サーバが ``Content-Disposition`` を返さなかったときの書き出しファイル名の拡張子。 */
const LIBRARY_FILE_SUFFIX = ".flwlib.json";

/**
 * ライブラリ全体の書き出し内容を取得する。
 *
 * @returns サーバが決めたファイル名 (``Content-Disposition``) とファイル本文。
 */
export async function exportLibrary(
  libraryName: string,
): Promise<{ filename: string; text: string }> {
  const response = await _fetchResponse(
    `/libraries/${encodeURIComponent(libraryName)}/export`,
  );
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  // フォールバックの名前はライブラリ名 (信頼できない文字列) から作るので、パス区切りや
  // ファイル名に使えない文字・制御文字を ``_`` に置換する
  const fallback = `${libraryName.replace(/[\\/:*?"<>|\p{Cc}\p{Cf}]/gu, "_")}${LIBRARY_FILE_SUFFIX}`;
  return {
    filename: match?.[1] ?? fallback,
    text: await response.text(),
  };
}
