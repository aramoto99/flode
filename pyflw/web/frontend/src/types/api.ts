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

// ADR-0020: 各 block の GUI 上の位置 (CSS px、React Flow 互換)。
export interface LayoutEntry {
  x: number;
  y: number;
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
