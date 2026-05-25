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

// ADR-0057: 手動 branch waypoint (分岐点 ● のドラッグ固定位置)。
// key = "<source block id>:<sourceHandle index>" (= 分岐点単位の合成キー、
// 区切り `:` は ADR-0004 の ID 規則で衝突しない)。value = flow 絶対座標 {x, y}。
// trunk 共有 (= 分岐点単位で 1 件、同一 source ポートの全枝が共有) で、欠落時は
// 全自動計算 (= 後方互換)。純粋な視覚情報で connections (トポロジ) には一切影響しない。
export type BranchWaypointDict = Record<string, { x: number; y: number }>;

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
  // ADR-0057: optional な手動 branch waypoint (合成キー → flow 絶対座標)。
  // top-level の独立キー (= layout / scope_settings と並ぶ)。backend は opaque
  // round-trip (= Python 無改修)。schema 0.8 維持 (optional 追加、bump 不要)。
  branch_waypoints?: BranchWaypointDict;
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
  // ADR-0021 §(5): drilldown / mask 可否のヒント
  is_container: boolean;
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
  /** ブロックタイプ (例: ``"pyflw.blocks.mathops.Divide"``)。 */
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
