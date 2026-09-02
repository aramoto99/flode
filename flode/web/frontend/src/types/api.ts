// ADR-0008 / ADR-0011 で定義された REST + WebSocket メッセージの型定義。

export interface BlockEntry {
  id: string;
  type: string;
  params: Record<string, unknown>;
}

export interface ConnectionEntry {
  src: string;
  src_idx: number;
  dst: string;
  dst_idx: number;
}

// ADR-0042 §論点 3-A: ``t_end`` は ``number | "inf"`` の Union。
// ``"inf"`` は unbounded run (Stop Time = ∞) を表す sentinel。frontend 内の
// 計算では ``parseTEnd`` ヘルパー (= ``timeUtil.ts``) で ``Number.POSITIVE_INFINITY``
// に正規化してから扱う。
export type TEnd = number | "inf";

export interface SimulatorConfig {
  t_end: TEnd;
  dt: number;
  solver: string;
  rtol: number;
  atol: number;
  dt_base: number | null;
}

// ADR-0020: 各 block の GUI 上の位置 + optional サイズ (CSS px、React Flow 互換)。
// ``w`` / ``h`` は NodeResizer でユーザーが手動リサイズしたときのみ書かれる。
// 欠落時は shape のデフォルトサイズを使う。
export interface LayoutEntry {
  x: number;
  y: number;
  w?: number;
  h?: number;
  // v0.15.0: ブロックの左右反転 (リファレンスツールの "Flip Block" 相当)。``true`` で
  // 入出力 port を反転、ノード内の SVG / text は読みやすさ維持のため再反転。
  // 純粋な GUI metadata で backend 計算には影響しない (= 接続先・接続元が同じ
  // なら結果は同じ)。``layout`` 配下に置くことで JSON schema 不変、optional
  // フィールドの追加で前方互換あり。
  flipped?: boolean;
}

// ADR-0044 §論点 4: per-signal の表示設定。Y 軸 / 凡例位置等は per-scope。
export type SignalMarker = "none" | "circle" | "square" | "cross";

export interface SignalSettings {
  /** CSS color string (= ``"#3b82f6"`` 等)、欠落時は uPlot 自動色 (8 色 fallback)。 */
  color?: string;
  /** 線幅 (1 / 2 / 3 px)、欠落時 1。 */
  width?: 1 | 2 | 3;
  /** マーカー形状、欠落時 ``"none"``。 */
  marker?: SignalMarker;
}

// ADR-0044 §論点 4 / §論点 7 / §論点 9: Scope のプロット設定 (per-scope)。
// 全フィールド optional、欠落時は ``DEFAULT_SCOPE_SETTINGS`` を使用。
export interface ScopeSettings {
  /** Y 軸スケール ``"auto"`` / ``"manual"`` / ``"log"`` (default ``"auto"``)。 */
  y_mode?: "auto" | "manual" | "log";
  /** ``y_mode === "manual"`` のときの min/max。 */
  y_min?: number;
  y_max?: number;
  /** X 軸スケール ``"auto"`` / ``"manual"`` (default ``"auto"``)。 */
  x_mode?: "auto" | "manual";
  x_min?: number;
  x_max?: number;
  /** 凡例位置 (default ``"top"``)。 */
  legend?: "top" | "bottom" | "right" | "off";
  /** メジャーグリッド (default true)。 */
  grid_major?: boolean;
  /** マイナーグリッド (default false)。 */
  grid_minor?: boolean;
  /** per-signal 設定。key は signal_idx (= 数値文字列、JSON 互換性のため string key)。 */
  signals?: Record<string, SignalSettings>;
}

export type LayoutDict = Record<string, LayoutEntry>;

// ADR-0057 (改訂 2026-05-25): 手動 branch waypoint (分岐点 ● のドラッグ固定位置)。
// key = "<source block id>:<sourceHandle index>" (= 分岐点単位の合成キー、
// 区切り `:` は ADR-0004 の ID 規則で衝突しない)。
//
// 値は **幹線方向に沿った 1 次元位置** ``{ axis, pos }``:
//   - ``axis``: 幹線方向 ("x" = 水平幹線 / "y" = 縦幹線)。現状の出力ポートは必ず
//     水平 (Right / flipped で Left) のため実質 "x"。縦幹線 ("y") はスキーマ上
//     受け入れる器のみ用意し router 実装は将来送り (ADR-0057 §改訂 §(改訂-D))。
//   - ``pos``: 幹線方向の絶対座標スカラ (水平なら flow X、縦なら flow Y)。直交成分は
//     保存せず描画時に source 出力高さ (sy/sx) で再構成する (= SSOT、R3)。
//
// ● は常に「線が実際に分かれる点 (= 幹線上)」に拘束される (R1)。trunk 共有
// (= 分岐点単位で 1 件、同一 source ポートの全枝が共有) で、欠落時は全自動計算。
// 純粋な視覚情報で connections (トポロジ) には一切影響しない。
//
// 後方互換: v1 で保存された旧形 ``{ x, y }`` は読込時に ``{ axis: "x", pos: x }``
// とみなし ``y`` を楽観無視する (= 水平幹線として解釈、次回 save で新形に正規化)。
export interface BranchWaypoint {
  axis: "x" | "y";
  pos: number;
}
export type BranchWaypointDict = Record<string, BranchWaypoint>;

export interface FlwModel {
  schema_version: string;
  metadata?: { name?: string; created_at?: string; tool?: string; comment?: string };
  simulator: SimulatorConfig;
  blocks: BlockEntry[];
  connections: ConnectionEntry[];
  // ADR-0020: optional な layout セクション (block_id → position)。欠落時は GUI 側の
  // grid auto-layout fallback で位置を算出する。
  layout?: LayoutDict;
  // ADR-0044 §論点 1: optional な per-scope プロット設定 (block_id → ScopeSettings)。
  // schema 0.8 維持 (= optional 追加なので bump 不要、ADR-0008 慣習)。
  scope_settings?: Record<string, ScopeSettings>;
  // ADR-0057: optional な手動 branch waypoint (合成キー → 幹線方向位置 {axis,pos})。
  // top-level の独立キー (= layout / scope_settings と並ぶ)。backend は opaque
  // round-trip (= Python 無改修)。schema 0.8 維持 (optional 追加、bump 不要)。
  branch_waypoints?: BranchWaypointDict;
  // ADR-0058 §論点 10: migrate_to_current() が 1 段以上 migration を適用したとき
  // に付与される元バージョン。frontend はこれを見て dirty flag を立て、toast を
  // 出してユーザーに「保存すると新 schema になる」と通知する。save 時には除去する。
  _migrated_from?: string;
}

export interface ModelList {
  models: string[];
}

export type SimulationStatus =
  | "running"
  | "completed"
  | "stopped"
  | "failed";

export interface SimulationState {
  simulation_id: string;
  model_id: string;
  status: SimulationStatus;
  current_t: number;
  // ADR-0042 §論点 3-A: backend が ``"inf"`` 文字列で配信する Union。
  t_end: TEnd;
  started_at: number;
  finished_at: number | null;
  error: string | null;
}

/**
 * ADR-0011 §(1): `GET /simulations/{id}/results` のレスポンス。
 * WS ストリームは queue 満杯時に古い scope_batch を drop しうるため、終端後に
 * この一括結果で Scope バッファを正とする (= サイレント欠損の補完)。
 * `values` は WS `scope_batch` と同じ行指向 (サンプル × 信号)。
 */
export interface SimulationResults {
  simulation_id: string;
  status: SimulationStatus;
  scopes: Record<
    string,
    { labels: string[]; times: number[]; values: number[][] }
  >;
}

// ADR-0019 §(1): Block class registry REST schema (palette UI / shape validation)
export interface BlockParamSpec {
  name: string;
  type: string;
  has_default: boolean;
  default: unknown;
  description: string;
  // ADR-0039 follow-up (v2.0.3): block class が ``_param_enums`` で
  // 許容値を宣言している場合、ParameterPanel が ``<select>`` で render する。
  // null / 未指定 (= キー不在) のとき従来 ``<input>``。
  enum_values?: string[];
}

// ADR-0028: Block 表示名・docstring summary の i18n (ja/en) 翻訳対応。
// ADR-0024 §(3) と整合した BCP47 短縮コード。
export type Locale = "en" | "ja";

export interface BlockMetadata {
  type_path: string;
  display_name: string;
  // ADR-0028 (schema blocks.v2、v0.11.0): locale → 表示名の翻訳テーブル。
  // 旧 schema (blocks.v1) では存在しないため optional。
  display_name_i18n?: Partial<Record<Locale, string>>;
  category: string;
  icon: string;
  // v0.33.0: per-block color は撤廃 (= category 増加時の palette 管理コスト
  // 削減 + 色覚多様性配慮 + design system 整合)。glyph 色は frontend 側で
  // slate-600 一色固定。
  docstring_summary: string;
  // ADR-0028: docstring 1 行説明の翻訳 (palette tooltip 等で使用)。
  docstring_summary_i18n?: Partial<Record<Locale, string>>;
  docstring_full?: string;
  params_spec: BlockParamSpec[];
  default_n_inputs: number;
  default_n_outputs: number;
  port_shapes_in_default: number[][];
  port_shapes_out_default: number[][];
  tags: string[];
  // 検索別名 (synonym)。display_name / type_path / category / tags に現れない
  // 同義語で palette / command palette / QuickAdd の検索ヒットを増やす
  // (例: "Relational" を "compare" / "比較" で発見可能にする)。
  // 旧サーバ (この field 以前) では欠落するため optional。
  search_keywords?: string[];
  // ADR-0021 §(5): drilldown / mask 可否のヒント
  is_container: boolean;
  // SPEC-0018 / ADR-0068 §A-1: 動的 n_inputs resolver 式 (optional)。
  // DSL: ``len(params.<attr_name>)`` のみ受理 (safe evaluator)。設定された
  // ブロックは drop 時 / params 編集時に port 数を再計算する。
  n_inputs_resolver?: string;
  mask_capable: boolean;
}

// ADR-0021 §(5)(7): Subsystem mask param 宣言と現在値
export interface MaskParamSpec {
  name: string;
  type: "float" | "int" | "bool";
  default: unknown;
  description: string;
}

export type MaskValuesDict = Record<string, number | boolean>;

export interface BlockRegistryResponse {
  blocks: BlockMetadata[];
  /** ``"blocks.v1"`` (legacy) または ``"blocks.v2"`` (ADR-0028)。 */
  schema_version: string;
  /** ADR-0028: サーバが対応する locale 一覧。``schema_version >= blocks.v2`` のみ。 */
  supported_locales?: Locale[];
}

// ADR-0029 (schema libraries.v1, v0.11.1):
// `.flwlib.json` で配布される マスク Subsystem 集合の REST 表現。
// `/api/v1/libraries` 系から取得する (= /api/v1/blocks とは責務分離)。

/** Library 内 1 entry の metadata (subsystem body は別 endpoint で取得)。 */
export interface LibraryEntryMetadata {
  id: string;
  display_name: string;
  display_name_i18n: Partial<Record<Locale, string>>;
  description: string;
  description_i18n: Partial<Record<Locale, string>>;
  /** ADR-0029 §CAT-A: ``library.<lib_name>.<suffix>`` の suffix 部分。
   *  空文字なら ``library.<lib_name>`` 直下に出る。 */
  category_suffix: string;
}

export interface LibraryMetadata {
  name: string;
  display_name: string;
  display_name_i18n: Partial<Record<Locale, string>>;
  description: string;
  description_i18n: Partial<Record<Locale, string>>;
  version: string;
  entries: LibraryEntryMetadata[];
}

export interface LibraryLoadError {
  path: string;
  message: string;
}

export interface LibraryRegistryResponse {
  libraries: LibraryMetadata[];
  load_errors: LibraryLoadError[];
  /** ``"libraries.v1"`` (Phase 4 v0.11.1)。 */
  schema_version: string;
  supported_locales: Locale[];
}

/** ``GET /api/v1/libraries/{lib}/{entry}`` の response。subsystem body 同梱。 */
export interface LibraryEntryDetail extends LibraryEntryMetadata {
  /** ``Subsystem.to_dict()`` の出力 (= ``{id, type, params}``、ADR-0029 §PLACE-A)。
   *  Inline 展開時に ``params`` 配下を ``BlockEntry`` の ``params`` フィールドへ
   *  そのままコピーする (= byte-identical 維持)。 */
  subsystem: {
    id: string | null;
    type: string;
    params: Record<string, unknown>;
  };
}

export interface ResolvedPortShapes {
  n_inputs: number;
  n_outputs: number;
  port_shapes_in: number[][];
  port_shapes_out: number[][];
}

// ADR-0056: シミュレーション失敗時の構造化エラー payload。
// WS の ``failed`` メッセージにマージされる + REST start API の ``detail`` にも同じ
// schema で入る。``category === "unknown"`` で fallback、frontend 未知の
// ``template_key`` は ``error.unknown`` に落とす (ADR-0056 §D-3)。
// SPEC-0023 / ADR-0073 §論点 1: PythonFunction の静的解析結果
// (``POST /api/v1/blocks/python-function/introspect``)。exec は行われない。
export interface PythonFunctionSpec {
  resolved: true;
  func_name: string;
  n_inputs: number;
  n_outputs: number;
  n_states: number;
  direct_feedthrough: boolean;
  sample_time: number | null;
  params_spec: BlockParamSpec[];
  // SPEC-0024 (後方互換の純粋追加): ポート名と編集可否 (サーバ判定)
  input_names: string[];
  output_names: string[];
  editable: {
    inputs: boolean;
    outputs: boolean;
    min_inputs: number;
    max_inputs: number;
    min_outputs: number;
    max_outputs: number;
  };
}

// SPEC-0024 §3.1: rewrite endpoint のレスポンス。``applied: false`` のとき
// ``code`` は返らない (元コードはクライアント側にある)。``kind`` の wire 語彙は
// 3 値に固定 (ADR-0074 §論点 3。自己検証失敗は "spec" に畳まれる)。
export type PythonFunctionRewriteResponse =
  | { applied: true; code: string; spec: PythonFunctionSpec }
  | {
      applied: false;
      error: {
        message: string;
        lineno: number | null;
        col: number | null;
        kind: "syntax" | "spec" | "unsupported";
      };
    };

export interface PythonFunctionSpecError {
  resolved: false;
  error: {
    message: string;
    lineno: number | null;
    col: number | null;
    /** "syntax" = 構文エラー / "spec" = 静的解析で受理できない (@block 0/2 個、語彙外注釈等) */
    kind: "syntax" | "spec";
  };
}

export type PythonFunctionIntrospectResult =
  | PythonFunctionSpec
  | PythonFunctionSpecError;

export interface PythonFunctionIntrospectResponse {
  results: Record<string, PythonFunctionIntrospectResult>;
}

export interface FailurePayload {
  /** Phase 1: algebraic_loop / shape_mismatch / divide_by_zero / solver_failure /
   *  start_validation / unknown */
  category: string;
  /** i18n キー (例: ``"error.divide_by_zero"``)。未知時は ``error.unknown`` fallback。 */
  template_key: string;
  /** i18next interpolation 用の引数 (block_label / t / shapes / reason 等)。 */
  template_args: Record<string, unknown>;
  /** 主因ブロック ID (= ``Simulator._current_block.id`` または ``AlgebraicLoopError.block_ids[0]``)。 */
  block_id: string | null;
  /** 関与ブロック ID 配列 (代数ループ等の複数関与)。単一なら 1 要素 / 不明なら空。 */
  block_ids: string[];
  /** ブロックタイプ (例: ``"flode.blocks.mathops.Divide"``)。 */
  block_type: string | null;
  /** ユーザー命名ラベル (= ``Block.name`` or ``id`` fallback)。 */
  block_label: string | null;
  /** 失敗発生時のシミュレーション時刻 (秒)。起動失敗は null。 */
  t: number | null;
  /** ``"{ExcType}: {str(e)}"`` 形式の生メッセージ (= compatibility / unknown fallback 用)。 */
  raw_message: string;
  /** サーバ traceback (truncated 末尾 50 行)。``include_traceback=False`` で null。 */
  raw_traceback: string | null;
}

// WebSocket メッセージ (ADR-0011 §(2))。
// ADR-0056: 旧 ``{type: "error", message}`` メッセージは廃止。
// ``failed`` メッセージは正常終了/失敗どちらでも届き、``category`` フィールドの
// 有無で失敗詳細を判別する (= ``FailurePayload`` を `Partial` でマージ)。
export type StreamMessage =
  // ADR-0042 §論点 3-A: ``t_end`` は ``number | "inf"`` Union。
  | { type: "progress"; current_t: number; t_end: TEnd }
  | {
      type: "scope_batch";
      scope_id: string;
      times: number[];
      values: number[][];
    }
  | { type: "completed"; duration_sec: number }
  | { type: "stopped"; duration_sec: number }
  | ({ type: "failed"; duration_sec: number } & Partial<FailurePayload>);
