// ADR-0081 §8-B: パレットの並び (ユーザーブロックのセクション・サブ見出し・組み込み
// カテゴリ) と、サーバ由来の信頼できない文字列の整形 (lib/untrustedText.ts)。

import { describe, expect, it } from "vitest";

import { cleanServerText } from "../src/lib/untrustedText";
import {
  buildPaletteLayout,
  choiceLabels,
  isUserBlock,
  orderSources,
  toLocale,
  userBlockDisplayName,
} from "../src/lib/userBlocks";
import type { BlockMetadata, BlockSourceInfo } from "../src/types/api";

const ORDER = ["sources", "mathops", "sinks", "uncategorized"] as const;
// 双方向制御文字 (RLO / LRI) と制御文字はコード上でも見えるよう文字コードで作る
const RLO = String.fromCharCode(0x202e);
const LRI = String.fromCharCode(0x2066);
const BEL = String.fromCharCode(0x07);

function meta(over: Partial<BlockMetadata> & { type_path: string }): BlockMetadata {
  return {
    display_name: over.type_path.split(".").at(-1) ?? over.type_path,
    category: "",
    icon: "default",
    docstring_summary: "",
    params_spec: [],
    default_n_inputs: 1,
    default_n_outputs: 1,
    port_shapes_in_default: [[]],
    port_shapes_out_default: [[]],
    tags: [],
    is_container: false,
    mask_capable: false,
    ...over,
  };
}

function source(over: Partial<BlockSourceInfo> & { id: string }): BlockSourceInfo {
  return {
    kind: "workspace",
    label: "blocks/",
    root: null,
    reloadable: true,
    from_cwd: false,
    files: [],
    ...over,
  };
}

const nameOf = (b: BlockMetadata): string => b.display_name;

describe("cleanServerText", () => {
  it("removes control and bidi characters and folds line breaks", () => {
    expect(cleanServerText(`a${RLO}b${LRI}c${BEL}\n\td`, 80)).toBe("abc d");
  });

  it("truncates by code point with an ellipsis", () => {
    expect(cleanServerText("abcdef", 4)).toBe("abc…");
    // サロゲートペア (絵文字) を分断しない
    expect(cleanServerText("😀😀😀", 2)).toBe("😀…");
    expect(cleanServerText("abc", 3)).toBe("abc");
  });

  it("returns an empty string for non-strings", () => {
    expect(cleanServerText(null, 10)).toBe("");
    expect(cleanServerText(42, 10)).toBe("");
    expect(cleanServerText({ a: 1 }, 10)).toBe("");
  });
});

describe("isUserBlock / userBlockDisplayName", () => {
  it("treats missing or builtin source as builtin", () => {
    expect(isUserBlock({})).toBe(false);
    expect(isUserBlock({ source: "builtin" })).toBe(false);
    expect(isUserBlock({ source: "workspace" })).toBe(true);
    expect(isUserBlock({ source: "module:mypkg" })).toBe(true);
  });

  it("cleans the display name and falls back when it becomes empty", () => {
    const b = meta({
      type_path: "flode_ws.f.Avg",
      source: "workspace",
      display_name: `${RLO}${BEL}`,
      display_name_i18n: { ja: `移動${RLO}平均` },
    });
    expect(userBlockDisplayName(b, "ja")).toBe("移動平均");
    expect(userBlockDisplayName(b, "en")).toBe("flode_ws.f.Avg");
    expect(toLocale("ja-JP")).toBe("ja");
    expect(toLocale(undefined)).toBe("en");
  });
});

describe("userBlockDisplayName fallback / choiceLabels", () => {
  it("falls back to '?' when every name cleans to an empty string", () => {
    const b = meta({ type_path: `${RLO}${BEL}`, source: "workspace", display_name: BEL });
    expect(userBlockDisplayName(b, "en")).toBe("?");
  });

  it("keeps distinct, non-empty labels as cleaned text", () => {
    expect(choiceLabels(["fast", `slo${RLO}w`])).toEqual(["fast", "slow"]);
  });

  it("uses the JSON form for labels that clean to empty or collide", () => {
    expect(choiceLabels(["", "a"])).toEqual(['""', "a"]);
    expect(choiceLabels([BEL, "x"])).toEqual(['"\\u0007"', "x"]);
    // "a<RLO>b" と "ab" は整形後に同じ → JSON 形でも同じなので位置番号を付ける
    expect(choiceLabels([`a${RLO}b`, "ab"])).toEqual(['"ab" #1', '"ab" #2']);
  });

  it("disambiguates values whose truncated prefixes are equal", () => {
    const long = "x".repeat(100);
    const labels = choiceLabels([`${long}1`, `${long}2`]);
    expect(new Set(labels).size).toBe(2);
    expect(labels.every((l) => l !== "")).toBe(true);
  });
});

describe("orderSources", () => {
  it("orders workspace -> dirs -> modules, keeping the server order within a kind", () => {
    const ordered = orderSources([
      source({ id: "module:b", kind: "module", label: "b" }),
      source({ id: "dir:z", kind: "dir", label: "z" }),
      source({ id: "module:a", kind: "module", label: "a" }),
      source({ id: "workspace" }),
      source({ id: "dir:a", kind: "dir", label: "a" }),
    ]);
    expect(ordered.map((s) => s.id)).toEqual([
      "workspace",
      "dir:z",
      "dir:a",
      "module:b",
      "module:a",
    ]);
  });
});

describe("buildPaletteLayout", () => {
  const sources = [
    source({ id: "module:pkg", kind: "module", label: "pkg" }),
    source({ id: "workspace" }),
    source({ id: "dir:lab", kind: "dir", label: "lab" }),
  ];

  it("puts user sections first, direct blocks before sorted category sub-headings", () => {
    const blocks = [
      meta({ type_path: "flode.blocks.Gain", category: "mathops", source: "builtin" }),
      meta({ type_path: "flode_ws.a.Zed", source: "workspace", category: "filters" }),
      meta({ type_path: "flode_ws.a.Bee", source: "workspace", category: "Analysis" }),
      meta({ type_path: "flode_ws.a.Plain", source: "workspace" }),
      meta({ type_path: "flode_ws.a.Alpha", source: "workspace", category: "filters" }),
      meta({ type_path: "pkg.X", source: "module:pkg" }),
    ];
    const layout = buildPaletteLayout({ sources }, blocks, {
      categoryOrder: ORDER,
      filtering: false,
      nameOf,
    });
    expect(layout.userSections.map((s) => s.id)).toEqual([
      "workspace",
      "dir:lab",
      "module:pkg",
    ]);
    const ws = layout.userSections[0]!;
    expect(ws.count).toBe(4);
    expect(ws.direct.map((b) => b.type_path)).toEqual(["flode_ws.a.Plain"]);
    // 文字列の昇順 (code point 順: 大文字が先)、カテゴリ内は表示名順
    expect(ws.groups.map((g) => g.category)).toEqual(["Analysis", "filters"]);
    expect(ws.groups[1]!.blocks.map((b) => b.display_name)).toEqual(["Alpha", "Zed"]);
    // ブロック 0 件の読み込み元も (検索中でなければ) セクションとして返す
    const lab = layout.userSections[1]!;
    expect(lab.count).toBe(0);
    expect(layout.builtinGroups.map((g) => g.category)).toEqual(["mathops"]);
  });

  it("drops empty sections while filtering", () => {
    const layout = buildPaletteLayout(
      { sources },
      [meta({ type_path: "flode_ws.a.Plain", source: "workspace" })],
      { categoryOrder: ORDER, filtering: true, nameOf },
    );
    expect(layout.userSections.map((s) => s.id)).toEqual(["workspace"]);
  });

  it("returns no user section when there is neither a source nor a user block", () => {
    const layout = buildPaletteLayout(
      { sources: [] },
      [meta({ type_path: "flode.blocks.Gain", category: "mathops" })],
      { categoryOrder: ORDER, filtering: false, nameOf },
    );
    expect(layout.userSections).toEqual([]);
  });

  it("keeps user blocks whose source is not listed in sources (not silently dropped)", () => {
    const layout = buildPaletteLayout(
      { sources: undefined },
      [meta({ type_path: "x.Y", source: "dir:ghost" })],
      { categoryOrder: ORDER, filtering: false, nameOf },
    );
    expect(layout.userSections).toHaveLength(1);
    expect(layout.userSections[0]!.source).toBeNull();
    expect(layout.userSections[0]!.id).toBe("dir:ghost");
  });

  it("shows builtin categories outside the order just before uncategorized", () => {
    const blocks = [
      meta({ type_path: "a.Other", category: "uncategorized" }),
      meta({ type_path: "a.Zeta", category: "zeta" }),
      meta({ type_path: "a.Alpha", category: "alpha" }),
      meta({ type_path: "a.Src", category: "sources" }),
      meta({ type_path: "a.Empty", category: "" }),
    ];
    const layout = buildPaletteLayout({ sources: [] }, blocks, {
      categoryOrder: ORDER,
      filtering: false,
      nameOf,
    });
    expect(layout.builtinGroups.map((g) => g.category)).toEqual([
      "sources",
      "alpha",
      "zeta",
      "uncategorized",
    ]);
    // 空カテゴリの組み込みブロックは「その他」に入る
    expect(layout.builtinGroups.at(-1)!.blocks.map((b) => b.type_path)).toEqual([
      "a.Empty",
      "a.Other",
    ]);
  });

  it("groups user categories by their cleaned text", () => {
    const layout = buildPaletteLayout(
      { sources: [source({ id: "workspace" })] },
      [
        meta({ type_path: "w.A", source: "workspace", category: `io${RLO}` }),
        meta({ type_path: "w.B", source: "workspace", category: "io" }),
        meta({ type_path: "w.C", source: "workspace", category: `${BEL}` }),
      ],
      { categoryOrder: ORDER, filtering: false, nameOf },
    );
    const ws = layout.userSections[0]!;
    expect(ws.groups.map((g) => g.category)).toEqual(["io"]);
    expect(ws.groups[0]!.blocks).toHaveLength(2);
    // 整形で空になったカテゴリは未宣言 (セクション直下)
    expect(ws.direct.map((b) => b.type_path)).toEqual(["w.C"]);
  });
});
