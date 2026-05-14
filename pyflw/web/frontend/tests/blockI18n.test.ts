// ADR-0028: blockI18n.ts のテスト。
// localizedDisplayName / localizedDocstringSummary / searchableDisplayNames の
// フォールバック chain を検証する。
//
// 言語切替の reactivity (= ``i18n.language`` 変化で再 render) は React component
// 側 (BlockPalette / QuickAdd) の責務なので、ここでは ``lang`` 引数指定での
// pure 関数挙動のみを検証する。

import { describe, expect, it } from "vitest";

import {
  localizedDisplayName,
  localizedDocstringSummary,
  searchableDisplayNames,
} from "../src/lib/blockI18n";
import type { BlockMetadata } from "../src/types/api";

const FULL: BlockMetadata = {
  type_path: "pyflw.blocks.sources.Constant",
  display_name: "Constant",
  display_name_i18n: { en: "Constant", ja: "定数" },
  category: "sources",
  icon: "sources.constant",
  docstring_summary: "Constant value source y(t) = value.",
  docstring_summary_i18n: {
    en: "Constant value source y(t) = value.",
    ja: "定数値ソース y(t) = value。",
  },
  params_spec: [],
  default_n_inputs: 0,
  default_n_outputs: 1,
  port_shapes_in_default: [],
  port_shapes_out_default: [[]],
  tags: ["sm_a", "source"],
  is_container: false,
  mask_capable: false,
};

// 旧サーバ (schema blocks.v1) からのレスポンス想定: i18n フィールドなし
const LEGACY: BlockMetadata = {
  ...FULL,
  display_name_i18n: undefined,
  docstring_summary_i18n: undefined,
};

describe("localizedDisplayName", () => {
  it("returns the locale-specific name when present", () => {
    expect(localizedDisplayName(FULL, "ja")).toBe("定数");
    expect(localizedDisplayName(FULL, "en")).toBe("Constant");
  });

  it("falls back to display_name when i18n is missing for that locale", () => {
    const partial: BlockMetadata = {
      ...FULL,
      display_name_i18n: { en: "Constant" }, // ja 未登録
    };
    expect(localizedDisplayName(partial, "ja")).toBe("Constant");
  });

  it("falls back to display_name when i18n is missing entirely (legacy server)", () => {
    expect(localizedDisplayName(LEGACY, "ja")).toBe("Constant");
    expect(localizedDisplayName(LEGACY, "en")).toBe("Constant");
  });

  it("falls back to type_path when both i18n and display_name are absent", () => {
    const stripped: BlockMetadata = {
      ...LEGACY,
      display_name: "",
    };
    expect(localizedDisplayName(stripped, "ja")).toBe(
      "pyflw.blocks.sources.Constant",
    );
  });
});

describe("localizedDocstringSummary", () => {
  it("returns the locale-specific summary when present", () => {
    expect(localizedDocstringSummary(FULL, "ja")).toBe(
      "定数値ソース y(t) = value。",
    );
  });

  it("falls back to docstring_summary when i18n missing", () => {
    expect(localizedDocstringSummary(LEGACY, "ja")).toBe(
      "Constant value source y(t) = value.",
    );
  });

  it("falls back to docstring_summary when i18n value is empty string", () => {
    const empty: BlockMetadata = {
      ...FULL,
      docstring_summary_i18n: { en: "", ja: "" },
    };
    // 空文字も missing 扱い (||) で次フォールバックの docstring_summary を返す
    expect(localizedDocstringSummary(empty, "ja")).toBe(
      "Constant value source y(t) = value.",
    );
  });

  it("returns empty string when nothing is available", () => {
    const empty: BlockMetadata = {
      ...LEGACY,
      docstring_summary: "",
    };
    expect(localizedDocstringSummary(empty, "ja")).toBe("");
  });
});

describe("searchableDisplayNames", () => {
  it("returns both locales plus the type_path tail", () => {
    const names = searchableDisplayNames(FULL);
    expect(names).toContain("Constant");
    expect(names).toContain("定数");
    // type_path 末尾も検索対象
    expect(names).toContain("Constant"); // tail "Constant" も同名なので 1 件に重複排除
  });

  it("deduplicates when ja and en are identical (e.g. Mux)", () => {
    const mux: BlockMetadata = {
      ...FULL,
      type_path: "pyflw.blocks.routing.Mux",
      display_name: "Mux",
      display_name_i18n: { en: "Mux", ja: "Mux" },
    };
    const names = searchableDisplayNames(mux);
    // "Mux" が ja/en/tail で 3 候補とも同じ → 1 件に重複排除
    expect(names).toEqual(["Mux"]);
  });

  it("works on legacy entries with no i18n field", () => {
    const names = searchableDisplayNames(LEGACY);
    expect(names).toContain("Constant");
    // legacy 互換: display_name + tail のみ (ja/en どちらも追加されない)
    expect(names.length).toBeGreaterThan(0);
  });
});
