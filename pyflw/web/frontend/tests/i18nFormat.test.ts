// ADR-0056 §D-1: i18next interpolation.format formatter (t_sec / block_labels)。

import { beforeAll, describe, expect, it } from "vitest";

import i18n from "../src/i18n";

beforeAll(async () => {
  await i18n.changeLanguage("ja");
});

describe("i18n interpolation.format", () => {
  it("t_sec formats numeric to 3 decimal places + 's'", () => {
    const out = i18n.t("error.divide_by_zero", { block_label: "X", t: 0.1 });
    expect(out).toContain("t=0.100s");
  });

  it("block_labels joins array with ', '", () => {
    const out = i18n.t("error.algebraic_loop", { block_labels: ["a", "b"] });
    expect(out).toContain("a, b");
  });

  it("t_sec falls back gracefully on non-numeric input", () => {
    const out = i18n.t("error.divide_by_zero", { block_label: "X", t: "NaN" });
    // 数値変換不能なら入力値を素通り
    expect(out).toContain("NaN");
  });
});
