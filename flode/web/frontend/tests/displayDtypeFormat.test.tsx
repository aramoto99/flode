// SPEC-0028 Q8: Display の表示整形が解決済み dtype に従う (記録は float64 のまま)。

import { describe, expect, it } from "vitest";

import { formatDisplayValue } from "../src/components/BlockNodeView";

describe("formatDisplayValue (SPEC-0028 Q8)", () => {
  it("integer dtypes render without decimals", () => {
    expect(formatDisplayValue(7.0, "int32")).toBe("7");
    expect(formatDisplayValue(-3.0, "int64")).toBe("-3");
    expect(formatDisplayValue(255.0, "uint8")).toBe("255");
  });

  it("bool renders true/false", () => {
    expect(formatDisplayValue(1.0, "bool")).toBe("true");
    expect(formatDisplayValue(0.0, "bool")).toBe("false");
  });

  it("float64 / unknown dtype keep the legacy 3-decimal formatting", () => {
    expect(formatDisplayValue(7.0, "float64")).toBe("7.000");
    expect(formatDisplayValue(7.0, null)).toBe("7.000");
    expect(formatDisplayValue(7.0)).toBe("7.000");
  });

  it("exponential formatting is preserved for extreme magnitudes", () => {
    expect(formatDisplayValue(123456.0, null)).toBe("1.23e+5");
    expect(formatDisplayValue(0.0001, null)).toBe("1.00e-4");
  });

  it("non-finite values pass through", () => {
    expect(formatDisplayValue(Number.NaN, "int32")).toBe("NaN");
    expect(formatDisplayValue(Number.POSITIVE_INFINITY, null)).toBe("Infinity");
  });
});
