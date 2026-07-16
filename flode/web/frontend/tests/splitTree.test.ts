// ADR-0045 §(10) Vitest: SplitTree 純関数の全パターンテスト
// (= 葉 0 / 1 / 2 / 3、ネスト深さ 0 / 1 / 2、JSON 往復、不正データ fallback)

import { describe, expect, it } from "vitest";

import {
  chooseInitialTree,
  DEFAULT_TREE,
  DEFAULT_TREE_WITH_SCOPES,
  deserializeTree,
  findLeaf,
  getLeafPaneIds,
  insertSplit,
  makeSplitId,
  normalizeTree,
  removeLeaf,
  serializeTree,
  setSplitRatio,
  toggleSplitOrientation,
  type SplitNode,
  type SplitTree,
} from "../src/lib/splitTree";

describe("DEFAULT_TREE / DEFAULT_TREE_WITH_SCOPES", () => {
  it("DEFAULT_TREE は diagram 葉単独", () => {
    expect(DEFAULT_TREE).toEqual({ kind: "leaf", paneId: "diagram" });
  });

  it("DEFAULT_TREE_WITH_SCOPES は diagram + scopes-stack の縦 60/40", () => {
    expect(DEFAULT_TREE_WITH_SCOPES).toEqual({
      kind: "split",
      orientation: "vertical",
      ratio: 0.6,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "scopes-stack" },
    });
  });
});

describe("getLeafPaneIds", () => {
  it("単一葉なら 1 要素", () => {
    expect(getLeafPaneIds(DEFAULT_TREE)).toEqual(["diagram"]);
  });

  it("split node の場合は a → b の深さ優先順", () => {
    expect(getLeafPaneIds(DEFAULT_TREE_WITH_SCOPES)).toEqual([
      "diagram",
      "scopes-stack",
    ]);
  });

  it("2 段ネストでも順序が保たれる", () => {
    const tree: SplitTree = {
      kind: "split",
      orientation: "horizontal",
      ratio: 0.5,
      a: { kind: "leaf", paneId: "diagram" },
      b: {
        kind: "split",
        orientation: "vertical",
        ratio: 0.5,
        a: { kind: "leaf", paneId: "scope:s1" },
        b: { kind: "leaf", paneId: "scope:s2" },
      },
    };
    expect(getLeafPaneIds(tree)).toEqual([
      "diagram",
      "scope:s1",
      "scope:s2",
    ]);
  });
});

describe("findLeaf", () => {
  it("存在する paneId は true", () => {
    expect(findLeaf(DEFAULT_TREE_WITH_SCOPES, "diagram")).toBe(true);
    expect(findLeaf(DEFAULT_TREE_WITH_SCOPES, "scopes-stack")).toBe(true);
  });
  it("存在しない paneId は false", () => {
    expect(findLeaf(DEFAULT_TREE_WITH_SCOPES, "scope:x")).toBe(false);
  });
});

describe("insertSplit", () => {
  it("単一葉を split right で 2 ペイン化 (新葉は b 側)", () => {
    const result = insertSplit(
      DEFAULT_TREE,
      "diagram",
      "horizontal",
      "scope:s1",
      "after",
    );
    expect(result).toEqual({
      kind: "split",
      orientation: "horizontal",
      ratio: 0.5,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "scope:s1" },
    });
  });

  it("position=before なら新葉が a 側 (左 or 上)", () => {
    const result = insertSplit(
      DEFAULT_TREE,
      "diagram",
      "vertical",
      "scope:s1",
      "before",
    );
    expect(getLeafPaneIds(result)).toEqual(["scope:s1", "diagram"]);
  });

  it("既存 split tree の特定葉に対しても再帰的に挿入", () => {
    const result = insertSplit(
      DEFAULT_TREE_WITH_SCOPES,
      "scopes-stack",
      "horizontal",
      "scope:s1",
      "after",
    );
    expect(getLeafPaneIds(result)).toEqual([
      "diagram",
      "scopes-stack",
      "scope:s1",
    ]);
  });

  it("存在しない target paneId なら元 tree を返す", () => {
    const result = insertSplit(
      DEFAULT_TREE,
      "nonexistent",
      "horizontal",
      "scope:s1",
      "after",
    );
    expect(result).toBe(DEFAULT_TREE);
  });

  it("paneId 重複 (= 同じ葉を再挿入) なら元 tree を返す", () => {
    const result = insertSplit(
      DEFAULT_TREE_WITH_SCOPES,
      "diagram",
      "horizontal",
      "scopes-stack",
      "after",
    );
    expect(result).toBe(DEFAULT_TREE_WITH_SCOPES);
  });
});

describe("removeLeaf", () => {
  it("単一葉の tree から葉を除去すると null", () => {
    expect(removeLeaf(DEFAULT_TREE, "diagram")).toBeNull();
  });

  it("2 ペイン構成から 1 ペインに縮約 (兄弟が昇格)", () => {
    const result = removeLeaf(DEFAULT_TREE_WITH_SCOPES, "scopes-stack");
    expect(result).toEqual({ kind: "leaf", paneId: "diagram" });
  });

  it("3 ペイン構成から中央葉を除去すると 2 ペイン残る", () => {
    const tree: SplitTree = {
      kind: "split",
      orientation: "horizontal",
      ratio: 0.5,
      a: { kind: "leaf", paneId: "diagram" },
      b: {
        kind: "split",
        orientation: "vertical",
        ratio: 0.5,
        a: { kind: "leaf", paneId: "scope:s1" },
        b: { kind: "leaf", paneId: "scope:s2" },
      },
    };
    const result = removeLeaf(tree, "scope:s1");
    expect(result).toEqual({
      kind: "split",
      orientation: "horizontal",
      ratio: 0.5,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "scope:s2" },
    });
  });

  it("存在しない葉なら元 tree をそのまま返す", () => {
    const result = removeLeaf(DEFAULT_TREE_WITH_SCOPES, "nonexistent");
    expect(result).toEqual(DEFAULT_TREE_WITH_SCOPES);
  });
});

describe("setSplitRatio", () => {
  it("split id 一致なら ratio 更新", () => {
    const id = makeSplitId(DEFAULT_TREE_WITH_SCOPES as SplitNode);
    const result = setSplitRatio(DEFAULT_TREE_WITH_SCOPES, id, 0.3);
    expect(result).toMatchObject({ ratio: 0.3 });
  });

  it("ratio < 0.05 なら clamp", () => {
    const id = makeSplitId(DEFAULT_TREE_WITH_SCOPES as SplitNode);
    const result = setSplitRatio(DEFAULT_TREE_WITH_SCOPES, id, 0.01);
    expect(result).toMatchObject({ ratio: 0.05 });
  });

  it("ratio > 0.95 なら clamp", () => {
    const id = makeSplitId(DEFAULT_TREE_WITH_SCOPES as SplitNode);
    const result = setSplitRatio(DEFAULT_TREE_WITH_SCOPES, id, 0.99);
    expect(result).toMatchObject({ ratio: 0.95 });
  });

  it("葉単独 tree は変化なし (= split id が存在しない)", () => {
    const result = setSplitRatio(DEFAULT_TREE, "split:x", 0.3);
    expect(result).toBe(DEFAULT_TREE);
  });
});

describe("toggleSplitOrientation", () => {
  it("vertical を horizontal に切替", () => {
    const id = makeSplitId(DEFAULT_TREE_WITH_SCOPES as SplitNode);
    const result = toggleSplitOrientation(DEFAULT_TREE_WITH_SCOPES, id);
    expect(result).toMatchObject({ orientation: "horizontal" });
  });

  it("再 toggle で vertical に戻る (idempotence over 2)", () => {
    const id = makeSplitId(DEFAULT_TREE_WITH_SCOPES as SplitNode);
    const once = toggleSplitOrientation(DEFAULT_TREE_WITH_SCOPES, id);
    const twice = toggleSplitOrientation(once, id);
    expect(twice).toEqual(DEFAULT_TREE_WITH_SCOPES);
  });
});

describe("serialize / deserialize", () => {
  it("JSON 往復で同型", () => {
    const json = serializeTree(DEFAULT_TREE_WITH_SCOPES);
    const restored = deserializeTree(json);
    expect(restored).toEqual(DEFAULT_TREE_WITH_SCOPES);
  });

  it("3 ペイン構成も JSON 往復で同型", () => {
    const tree: SplitTree = {
      kind: "split",
      orientation: "horizontal",
      ratio: 0.7,
      a: { kind: "leaf", paneId: "diagram" },
      b: {
        kind: "split",
        orientation: "vertical",
        ratio: 0.4,
        a: { kind: "leaf", paneId: "scope:s1" },
        b: { kind: "leaf", paneId: "scope:s2" },
      },
    };
    const json = serializeTree(tree);
    expect(deserializeTree(json)).toEqual(tree);
  });

  it("null / undefined / 空文字列は null を返す", () => {
    expect(deserializeTree(null)).toBeNull();
    expect(deserializeTree(undefined)).toBeNull();
    expect(deserializeTree("")).toBeNull();
  });

  it("不正な JSON 構造は null を返す", () => {
    expect(deserializeTree("not-json")).toBeNull();
    expect(deserializeTree("{}")).toBeNull();
    expect(deserializeTree('{"kind":"unknown"}')).toBeNull();
  });

  it("ratio が範囲外でも JSON 復元時に弾く (= isSplitTree が strict)", () => {
    expect(
      deserializeTree(
        '{"kind":"split","orientation":"vertical","ratio":0,"a":{"kind":"leaf","paneId":"x"},"b":{"kind":"leaf","paneId":"y"}}',
      ),
    ).toBeNull();
    expect(
      deserializeTree(
        '{"kind":"split","orientation":"vertical","ratio":1.5,"a":{"kind":"leaf","paneId":"x"},"b":{"kind":"leaf","paneId":"y"}}',
      ),
    ).toBeNull();
  });

  it("葉 paneId が重複している不正データは normalize で重複除去", () => {
    const json =
      '{"kind":"split","orientation":"vertical","ratio":0.5,"a":{"kind":"leaf","paneId":"diagram"},"b":{"kind":"leaf","paneId":"diagram"}}';
    const restored = deserializeTree(json);
    expect(restored).toEqual({ kind: "leaf", paneId: "diagram" });
  });
});

describe("normalizeTree", () => {
  it("葉単独はそのまま", () => {
    expect(normalizeTree(DEFAULT_TREE)).toEqual(DEFAULT_TREE);
  });

  it("両葉が同一 paneId なら片方が消えて葉単独に縮約", () => {
    const tree: SplitTree = {
      kind: "split",
      orientation: "vertical",
      ratio: 0.5,
      a: { kind: "leaf", paneId: "diagram" },
      b: { kind: "leaf", paneId: "diagram" },
    };
    expect(normalizeTree(tree)).toEqual({ kind: "leaf", paneId: "diagram" });
  });

  it("葉が 1 つも生き残らない (= 全葉同一) ケースは null ではなく単葉になる (最初の出現が残るため)", () => {
    expect(normalizeTree(DEFAULT_TREE)).toEqual(DEFAULT_TREE);
  });
});

describe("chooseInitialTree", () => {
  it("stored が valid SplitTree なら復元優先", () => {
    const stored = serializeTree({
      kind: "leaf",
      paneId: "diagram",
    });
    expect(chooseInitialTree(stored, true)).toEqual({
      kind: "leaf",
      paneId: "diagram",
    });
  });

  it("stored が不正 JSON なら Scope 有無の default にフォールバック", () => {
    expect(chooseInitialTree("not-json", true)).toEqual(
      DEFAULT_TREE_WITH_SCOPES,
    );
  });

  it("stored 無し、Scope 有りなら DEFAULT_TREE_WITH_SCOPES", () => {
    expect(chooseInitialTree(null, true)).toEqual(DEFAULT_TREE_WITH_SCOPES);
  });

  it("stored 無し、Scope 無しなら DEFAULT_TREE (diagram 単独)", () => {
    expect(chooseInitialTree(null, false)).toEqual(DEFAULT_TREE);
  });
});
