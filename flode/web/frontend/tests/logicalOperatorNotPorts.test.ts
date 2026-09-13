// bug-fix 2026-09-13: LogicalOperator の operator を NOT にすると n_inputs=1 固定
// (logic.py) だが、frontend は既定 n_inputs=2 のまま送っていたため run / 保存時に
// BlockSpecError になり Inspector からは原因が見えなかった。
//   - resolvePortCounts: NOT のときはポート数 1 として描画・接続検証する
//   - withDependentParams: operator 変更時に n_inputs を追従させる
import { describe, expect, it } from "vitest";

import { isLogicalOperatorUnary, resolvePortCounts } from "../src/lib/dynamicPorts";
import { withDependentParams } from "../src/lib/paramEdit";

const LOGICAL = "flode.blocks.logic.LogicalOperator";

describe("LogicalOperator NOT の n_inputs 追従", () => {
  it("resolvePortCounts: NOT は n_inputs 値に関わらず 1 入力", () => {
    expect(resolvePortCounts(LOGICAL, { operator: "NOT", n_inputs: 2 }, undefined)).toEqual({
      nInputs: 1,
      nOutputs: 1,
    });
    expect(resolvePortCounts(LOGICAL, { operator: "AND", n_inputs: 3 }, undefined)).toEqual({
      nInputs: 3,
      nOutputs: 1,
    });
  });

  it("withDependentParams: AND→NOT で n_inputs=1、NOT→OR で 2 に戻る", () => {
    const andBlock = { id: "lo", type: LOGICAL, params: { operator: "AND", n_inputs: 2 } };
    expect(withDependentParams(andBlock, "operator", "NOT")).toEqual({
      operator: "NOT",
      n_inputs: 1,
    });
    const notBlock = { id: "lo", type: LOGICAL, params: { operator: "NOT", n_inputs: 1 } };
    expect(withDependentParams(notBlock, "operator", "OR")).toEqual({
      operator: "OR",
      n_inputs: 2,
    });
  });

  it("withDependentParams: 3 入力 AND → XOR は n_inputs を保つ", () => {
    const block = { id: "lo", type: LOGICAL, params: { operator: "AND", n_inputs: 3 } };
    expect(withDependentParams(block, "operator", "XOR")).toEqual({
      operator: "XOR",
      n_inputs: 3,
    });
  });

  it("withDependentParams: n_inputs 直接編集も clamp する (code-reviewer MUST)", () => {
    const notBlock = { id: "lo", type: LOGICAL, params: { operator: "NOT", n_inputs: 1 } };
    expect(withDependentParams(notBlock, "n_inputs", 3)).toEqual({
      operator: "NOT",
      n_inputs: 1,
    });
    const andBlock = { id: "lo", type: LOGICAL, params: { operator: "AND", n_inputs: 2 } };
    expect(withDependentParams(andBlock, "n_inputs", 1)).toEqual({
      operator: "AND",
      n_inputs: 2,
    });
    expect(withDependentParams(andBlock, "n_inputs", 4)).toEqual({
      operator: "AND",
      n_inputs: 4,
    });
  });

  it("isLogicalOperatorUnary は NOT のみ真", () => {
    expect(isLogicalOperatorUnary("NOT")).toBe(true);
    expect(isLogicalOperatorUnary("AND")).toBe(false);
    expect(isLogicalOperatorUnary(undefined)).toBe(false);
  });

  it("withDependentParams: 他ブロック / 他パラメータには触れない", () => {
    const sw = { id: "sw", type: "flode.blocks.routing.Switch", params: { criterion: ">=" } };
    expect(withDependentParams(sw, "criterion", ">")).toEqual({ criterion: ">" });
    const lo = { id: "lo", type: LOGICAL, params: { operator: "AND", n_inputs: 2 } };
    expect(withDependentParams(lo, "n_inputs", 4)).toEqual({ operator: "AND", n_inputs: 4 });
  });
});
