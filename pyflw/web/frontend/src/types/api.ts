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
}

export interface BlockMetadata {
  type_path: string;
  display_name: string;
  category: string;
  icon: string;
  color: string;
  docstring_summary: string;
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
  schema_version: string;
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
