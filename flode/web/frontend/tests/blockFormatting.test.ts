// ADR-0070: compareOpSymbol は CompareToConstant / CompareToZero /
// RelationalOperator の canvas 表示で共用される。backend の
// `RelationalOperator._ALLOWED_OPS` (flode/blocks/logic.py) と 1:1 で
// 網羅されていることを固定する (enum 追加時に "?" 表示へ静かに退化する回帰の防止)。
import { describe, expect, it } from "vitest";

import { compareOpSymbol } from "../src/lib/blockFormatting";

describe("compareOpSymbol", () => {
  // backend _ALLOWED_OPS 全 6 種 → JIS Z 8201 の数学記号 (== のみ = に短縮)
  it.each([
    ["<", "<"],
    ["<=", "≤"],
    ["==", "="],
    ["!=", "≠"],
    [">=", "≥"],
    [">", ">"],
  ])("maps %s to %s", (op, expected) => {
    expect(compareOpSymbol(op)).toBe(expected);
  });

  it.each([["<>"], [""], [undefined], [null], [42]])(
    "falls back to ? for unknown input %s",
    (op) => {
      expect(compareOpSymbol(op)).toBe("?");
    },
  );
});
