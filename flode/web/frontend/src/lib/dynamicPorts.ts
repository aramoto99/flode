// Block の現在 params から実 port 数を **ローカル** に算出する。
// REST `/api/v1/blocks/resolve-port-shapes` を毎回叩くより軽量で、ノード描画 / 接続
// 検証 / 配線剪定すべて同じ結果になる。
//
// ルールが Python 側 (flode/blocks/*) の ``__init__`` ロジックと一致している必要が
// あるため、ここでズレが生じたら Python 側の実装に合わせること。
// (= 各 endsWith の上に Python 実装の根拠コメントを書いておく)

import type { BlockEntry, BlockMetadata } from "../types/api";
import {
  ENABLE_TYPE,
  INPORT_TYPE,
  OUTPORT_TYPE,
  PYTHON_FUNCTION_TYPE,
  TRIGGER_TYPE,
} from "./blockTypes";
import { getCachedPythonSpec } from "./pythonFunctionSpec";

export interface ResolvedPortCounts {
  nInputs: number;
  nOutputs: number;
}

/**
 * LogicalOperator の単項演算子 (Python 側 ``logic.py`` の ``_UNARY_OPS`` と一致させる)。
 * 単項演算子は ``n_inputs=1`` 固定で、それ以外は ``n_inputs >= 2``。
 * ポート数の解決 (本ファイル) と Inspector の従属パラメータ追従
 * (``lib/paramEdit.ts`` の ``withDependentParams``) の両方がこの 1 箇所を参照する。
 */
export const LOGICAL_UNARY_OPERATORS: readonly string[] = ["NOT"];

/**
 * LogicalOperator の operator 値が単項 (= 1 入力固定) かを返す。
 *
 * @param operator - params.operator の値 (未設定 / 非文字列は false)
 */
export function isLogicalOperatorUnary(operator: unknown): boolean {
  return typeof operator === "string" && LOGICAL_UNARY_OPERATORS.includes(operator);
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
    // NOT は n_inputs=1 固定 (logic.py: NOT requires n_inputs=1)。bug-fix 2026-09-13:
    // Inspector で operator を NOT に変えた瞬間からポート数を 1 として扱い、
    // 「select で選べるのに backend が拒否する / 2 ポート目が幽霊化する」を防ぐ
    // (ParameterPanel 側でも n_inputs を 1 に追従させる)
    if (isLogicalOperatorUnary(params.operator)) return { nInputs: 1, nOutputs: 1 };
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

  // ----- Continuous -----
  // ADR-0079 D-9 (v0.64.0): StateSpace / DiscreteStateSpace / MimoTransferFunction は
  // 入力 1 本 / 出力 1 本のベクトルポート (shape は B / C / numerators の次元で
  // backend が宣言する) → registry default (1 / 1) をそのまま使う (分岐なし)。

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

  // ----- PythonFunction (SPEC-0023 / ADR-0073 §論点 1) -----
  // ポート数はコードの静的解析 (introspect API) で決まる。cache hit ならその値、
  // miss (= 解析中 / 未要求) なら registry default (1 in / 1 out)。
  // 解析エラーのコードも default で描く (= 結線を壊さない)。
  if (typePath === PYTHON_FUNCTION_TYPE) {
    const spec = getCachedPythonSpec(params.code);
    if (spec !== undefined && spec.resolved) {
      return { nInputs: spec.n_inputs, nOutputs: spec.n_outputs };
    }
    return { nInputs: defaultIn, nOutputs: defaultOut };
  }

  // それ以外は registry default
  return { nInputs: defaultIn, nOutputs: defaultOut };
}

/**
 * ``updateBlockParams`` の結線剪定を行ってよいか (SPEC-0023 / ADR-0073 V10 ガード)。
 *
 * PythonFunction は新コードの解析結果が cache に無いとポート数が「default に
 * 見える」だけで確定していないため、その状態で剪定すると結線を誤って落とす。
 * 解析済み (= PythonCodeDialog が Apply 前に cache へ投入) のときだけ true。
 */
export function canPruneOnParamChange(
  typePath: string,
  nextParams: Record<string, unknown>,
): boolean {
  if (typePath !== PYTHON_FUNCTION_TYPE) return true;
  const spec = getCachedPythonSpec(nextParams.code);
  return spec !== undefined && spec.resolved;
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
    ".Subsystem",
    ".PythonFunction",
  ].some((suffix) => typePath.endsWith(suffix));
}

function readPositiveInt(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v) && v >= 1) {
    return Math.trunc(v);
  }
  return fallback;
}
