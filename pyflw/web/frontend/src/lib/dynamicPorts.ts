// Block の現在 params から実 port 数を **ローカル** に算出する。
// REST `/api/v1/blocks/resolve-port-shapes` を毎回叩くより軽量で、ノード描画 / 接続
// 検証 / 配線剪定すべて同じ結果になる。
//
// ルールが Python 側 (pyflw/blocks/*) の ``__init__`` ロジックと一致している必要が
// あるため、ここでズレが生じたら Python 側の実装に合わせること。
// (= 各 endsWith の上に Python 実装の根拠コメントを書いておく)

import type { BlockEntry, BlockMetadata } from "../types/api";
import {
  ENABLE_TYPE,
  INPORT_TYPE,
  OUTPORT_TYPE,
  TRIGGER_TYPE,
} from "./blockTypes";

export interface ResolvedPortCounts {
  nInputs: number;
  nOutputs: number;
}

export function resolvePortCounts(
  typePath: string,
  params: Record<string, unknown>,
  meta: BlockMetadata | undefined,
): ResolvedPortCounts {
  const defaultIn = meta?.default_n_inputs ?? 1;
  const defaultOut = meta?.default_n_outputs ?? 1;

  // ----- Math -----
  // Sum: super().__init__(n_inputs=len(signs), n_outputs=1)  (mathops.py:47)
  if (typePath.endsWith(".Sum")) {
    const signs = typeof params.signs === "string" ? params.signs : "";
    if (signs.length > 0) return { nInputs: signs.length, nOutputs: 1 };
    return { nInputs: defaultIn, nOutputs: 1 };
  }
  // Product: n_inputs param (mathops.py:69)
  if (typePath.endsWith(".Product")) {
    return { nInputs: readPositiveInt(params.n_inputs, defaultIn), nOutputs: 1 };
  }
  // Divide: super().__init__(n_inputs=len(signs), n_outputs=1)  (mathops.py:196)
  if (typePath.endsWith(".Divide")) {
    const signs = typeof params.signs === "string" ? params.signs : "";
    if (signs.length > 0) return { nInputs: signs.length, nOutputs: 1 };
    return { nInputs: defaultIn, nOutputs: 1 };
  }
  // MinMax: n_inputs param (mathops.py:160)
  if (typePath.endsWith(".MinMax")) {
    return { nInputs: readPositiveInt(params.n_inputs, defaultIn), nOutputs: 1 };
  }

  // ----- Logic -----
  // LogicalOperator: n_inputs param (logic.py:92)
  if (typePath.endsWith(".LogicalOperator")) {
    // NOT は n_inputs=1 固定だが Python 側で検証されるので素直に n_inputs を使う
    return { nInputs: readPositiveInt(params.n_inputs, defaultIn), nOutputs: 1 };
  }

  // ----- Routing -----
  // Mux: super().__init__(n_inputs=n, n_outputs=1)  (routing.py:104)
  if (typePath.endsWith(".Mux")) {
    return { nInputs: readPositiveInt(params.n, 2), nOutputs: 1 };
  }
  // Demux: super().__init__(n_inputs=1, n_outputs=n)  (routing.py:159)
  if (typePath.endsWith(".Demux")) {
    return { nInputs: 1, nOutputs: readPositiveInt(params.n, 2) };
  }

  // ----- Sinks (n_inputs を可変) -----
  if (
    typePath.endsWith(".Scope") ||
    typePath.endsWith(".Display") ||
    typePath.endsWith(".Terminator")
  ) {
    return {
      nInputs: readPositiveInt(params.n_inputs, defaultIn),
      nOutputs: 0,
    };
  }

  // ----- Continuous: 行列形状から導出 -----
  // StateSpace: n_inputs = B.shape[1], n_outputs = C.shape[0]  (continuous.py:111)
  if (typePath.endsWith(".StateSpace")) {
    const ni = matrixCols(params.B) ?? defaultIn;
    const no = matrixRows(params.C) ?? defaultOut;
    return { nInputs: Math.max(1, ni), nOutputs: Math.max(1, no) };
  }
  // MimoTransferFunction: n_inputs = q (numerators[0].length), n_outputs = p (numerators.length)
  //                      (continuous.py:371)
  if (typePath.endsWith(".MimoTransferFunction")) {
    const num = params.numerators;
    if (Array.isArray(num) && num.length > 0) {
      const p = num.length;
      const q = Array.isArray(num[0]) ? (num[0] as unknown[]).length : 1;
      return { nInputs: Math.max(1, q), nOutputs: Math.max(1, p) };
    }
    return { nInputs: defaultIn, nOutputs: defaultOut };
  }
  // DiscreteStateSpace: 同 StateSpace (discrete.py:353)
  if (typePath.endsWith(".DiscreteStateSpace")) {
    const ni = matrixCols(params.B) ?? defaultIn;
    const no = matrixRows(params.C) ?? defaultOut;
    return { nInputs: Math.max(1, ni), nOutputs: Math.max(1, no) };
  }

  // ----- Subsystem (ADR-0039 派生 property + ADR-0058 control block) -----
  // 内部 Inport / Outport / Trigger / Enable から自動算出。
  // ADR-0058 §論点 4: slot 順序 [data_inports..., enable_slot, trigger_slot]。
  if (typePath.endsWith(".Subsystem")) {
    const inner = params.blocks;
    if (Array.isArray(inner)) {
      const inports = countByType(inner, INPORT_TYPE);
      const outports = countByType(inner, OUTPORT_TYPE);
      const hasTrigger = countByType(inner, TRIGGER_TYPE) > 0 ? 1 : 0;
      const hasEnable = countByType(inner, ENABLE_TYPE) > 0 ? 1 : 0;
      return { nInputs: inports + hasEnable + hasTrigger, nOutputs: outports };
    }
    return { nInputs: defaultIn, nOutputs: defaultOut };
  }

  // それ以外は registry default
  return { nInputs: defaultIn, nOutputs: defaultOut };
}

function countByType(blocks: unknown[], typePath: string): number {
  let n = 0;
  for (const b of blocks) {
    if (b && typeof b === "object" && (b as BlockEntry).type === typePath) {
      n += 1;
    }
  }
  return n;
}

/**
 * type_path が動的 port を持つかどうか (ParameterPanel が param 編集に追従させたい
 * かの判定に使う、現状では呼び出し側がない)。
 */
export function hasDynamicPorts(typePath: string): boolean {
  return [
    ".Sum",
    ".Product",
    ".Divide",
    ".MinMax",
    ".LogicalOperator",
    ".Mux",
    ".Demux",
    ".Scope",
    ".Display",
    ".Terminator",
    ".StateSpace",
    ".DiscreteStateSpace",
    ".MimoTransferFunction",
    ".Subsystem",
  ].some((suffix) => typePath.endsWith(suffix));
}

function readPositiveInt(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v) && v >= 1) {
    return Math.trunc(v);
  }
  return fallback;
}

/** 2D ndarray-like の列数 (= shape[1])。形状不正時 ``null``。 */
function matrixCols(v: unknown): number | null {
  if (!Array.isArray(v) || v.length === 0) return null;
  const row0 = v[0];
  if (!Array.isArray(row0)) return null;
  return row0.length;
}

/** 2D ndarray-like の行数 (= shape[0])。 */
function matrixRows(v: unknown): number | null {
  if (!Array.isArray(v)) return null;
  return v.length;
}
