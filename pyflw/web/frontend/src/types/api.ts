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

export interface SimulatorConfig {
  t_end: number;
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
  // v0.15.0: ブロックの左右反転 (Simulink の "Flip Block" 相当)。``true`` で
  // 入出力 port を反転、ノード内の SVG / text は読みやすさ維持のため再反転。
  // 純粋な GUI metadata で backend 計算には影響しない (= 接続先・接続元が同じ
  // なら結果は同じ)。``layout`` 配下に置くことで JSON schema 不変、optional
  // フィールドの追加で前方互換あり。
  flipped?: boolean;
}

export type LayoutDict = Record<string, LayoutEntry>;

export interface FlwModel {
  schema_version: string;
  metadata?: { name?: string; created_at?: string; tool?: string; comment?: string };
  simulator: SimulatorConfig;
  blocks: BlockEntry[];
  connections: ConnectionEntry[];
  // ADR-0020: optional な layout セクション (block_id → position)。欠落時は GUI 側の
  // grid auto-layout fallback で位置を算出する。
  layout?: LayoutDict;
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
  t_end: number;
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
  color: string;
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

// WebSocket メッセージ (ADR-0011 §(2))
// 終端メッセージ (completed / stopped / failed) には ``duration_sec`` も含まれるが、
// Phase 2 では UI に表示しないため store に保存していない (Phase 3 で表示予定)。
export type StreamMessage =
  | { type: "progress"; current_t: number; t_end: number }
  | {
      type: "scope_batch";
      scope_id: string;
      times: number[];
      values: number[][];
    }
  | { type: "completed"; duration_sec: number }
  | { type: "stopped"; duration_sec: number }
  | { type: "failed"; duration_sec: number }
  | { type: "error"; message: string };
