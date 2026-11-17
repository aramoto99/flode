// ADR-0086 §5-B / §6-B, SPEC-0037 受け入れ条件 5: 行エディタの純関数。
// - 末尾追加・途中削除・↑/↓・置き換えの対応表と、操作後の選択 (D6)
// - remapConnections: 範囲外は不変・削除行の配線は消える・同じ入力ポートに 2 本重ならない
// - remapBranchWaypoints: 出力側のキーを移し、削除行のキーは落とす
// - parseTextList (D7) と表示の対応 (位置 / 文字列)

import { describe, expect, it } from "vitest";

import {
  appendRow,
  deleteRow,
  displayRows,
  fieldValuesFor,
  formatTextList,
  MAX_PICK_VALUES,
  parseTextList,
  remapAppend,
  remapBranchWaypoints,
  remapConnections,
  remapDelete,
  remapSwap,
  replaceRow,
  swapRows,
  toRemaps,
  type IndexRemap,
} from "../src/lib/paramRows";
import type { ConnectionEntry, ParamRowsDescribeResponse, ParamRowsVariant } from "../src/types/api";

const ROWS = ["a", "b", "c", "d"];

describe("row operations and remaps", () => {
  it("append keeps every existing row and selects the new one", () => {
    const edit = appendRow(ROWS, "e");
    expect(edit.rows).toEqual(["a", "b", "c", "d", "e"]);
    expect(edit.map).toEqual([0, 1, 2, 3]);
    expect(edit.selected).toBe(4);
    expect(remapAppend(0)).toEqual([]);
  });

  it("delete in the middle drops that row and shifts the later rows up", () => {
    const edit = deleteRow(ROWS, 1);
    expect(edit.rows).toEqual(["a", "c", "d"]);
    expect(edit.map).toEqual([0, null, 1, 2]);
    expect(edit.selected).toBe(1);
  });

  it("delete of the last row selects the row above, and of the only row selects nothing", () => {
    expect(deleteRow(ROWS, 3).selected).toBe(2);
    expect(deleteRow(["x"], 0)).toEqual({ rows: [], map: [null], selected: null });
  });

  it("swap exchanges the two rows and their numbers", () => {
    const up = swapRows(ROWS, 2, 1);
    expect(up.rows).toEqual(["a", "c", "b", "d"]);
    expect(up.map).toEqual([0, 2, 1, 3]);
    expect(up.selected).toBe(1);
    expect(remapSwap(3, 0, 2)).toEqual([2, 1, 0]);
  });

  it("replace keeps the numbering", () => {
    const edit = replaceRow(ROWS, 2, "C");
    expect(edit.rows).toEqual(["a", "b", "C", "d"]);
    expect(edit.map).toEqual([0, 1, 2, 3]);
    expect(edit.selected).toBe(2);
  });

  it("rejects an out-of-range index", () => {
    expect(() => deleteRow(ROWS, 4)).toThrow(RangeError);
    expect(() => replaceRow(ROWS, -1, "x")).toThrow(RangeError);
    expect(() => swapRows(ROWS, 0, 9)).toThrow(RangeError);
  });

  it("toRemaps gives no remap when the rows do not map to ports", () => {
    expect(toRemaps(remapDelete(3, 1), null)).toEqual([]);
    expect(toRemaps(remapDelete(3, 1), "output")).toEqual([
      { side: "output", map: [0, null, 1] },
    ]);
  });
});

describe("remapConnections", () => {
  const conns: ConnectionEntry[] = [
    { src: "s0", src_idx: 0, dst: "B", dst_idx: 0 },
    { src: "s1", src_idx: 0, dst: "B", dst_idx: 1 },
    { src: "s2", src_idx: 0, dst: "B", dst_idx: 2 },
    { src: "s3", src_idx: 0, dst: "B", dst_idx: 3 },
    { src: "s9", src_idx: 0, dst: "B", dst_idx: 7 }, // 行に対応しない番号
    { src: "B", src_idx: 0, dst: "z", dst_idx: 0 }, // 出力側 (入力の対応表では触らない)
    { src: "s1", src_idx: 0, dst: "other", dst_idx: 1 }, // 別ブロック
  ];

  it("deleting a wired middle row removes its wire and keeps later wires on the same rows", () => {
    const remap: IndexRemap = { side: "input", map: deleteRow(ROWS, 1).map };
    const out = remapConnections(conns, "B", remap);
    expect(out).toEqual([
      { src: "s0", src_idx: 0, dst: "B", dst_idx: 0 },
      { src: "s2", src_idx: 0, dst: "B", dst_idx: 1 },
      { src: "s3", src_idx: 0, dst: "B", dst_idx: 2 },
      { src: "s9", src_idx: 0, dst: "B", dst_idx: 7 },
      { src: "B", src_idx: 0, dst: "z", dst_idx: 0 },
      { src: "s1", src_idx: 0, dst: "other", dst_idx: 1 },
    ]);
  });

  it("swap exchanges the wires and never stacks two wires on one input", () => {
    const out = remapConnections(conns, "B", { side: "input", map: swapRows(ROWS, 0, 1).map });
    const intoB = out.filter((c) => c.dst === "B").map((c) => [c.src, c.dst_idx]);
    expect(intoB).toEqual([
      ["s0", 1],
      ["s1", 0],
      ["s2", 2],
      ["s3", 3],
      ["s9", 7],
    ]);
    const idx = out.filter((c) => c.dst === "B").map((c) => c.dst_idx);
    expect(new Set(idx).size).toBe(idx.length);
  });

  it("append and replace leave the wires (and the array) unchanged", () => {
    expect(remapConnections(conns, "B", { side: "input", map: remapAppend(4) })).toBe(conns);
  });

  it("output remaps rewrite src_idx of the block's outgoing wires", () => {
    const out = remapConnections(
      [
        { src: "B", src_idx: 0, dst: "x", dst_idx: 0 },
        { src: "B", src_idx: 1, dst: "y", dst_idx: 0 },
        { src: "B", src_idx: 2, dst: "y", dst_idx: 1 },
      ],
      "B",
      { side: "output", map: remapDelete(3, 0) },
    );
    expect(out).toEqual([
      { src: "B", src_idx: 0, dst: "y", dst_idx: 0 },
      { src: "B", src_idx: 1, dst: "y", dst_idx: 1 },
    ]);
  });
});

describe("remapBranchWaypoints", () => {
  const wp = {
    "B:0": { axis: "x" as const, pos: 10 },
    "B:1": { axis: "x" as const, pos: 11 },
    "B:2": { axis: "y" as const, pos: 12 },
    "B:9": { axis: "y" as const, pos: 19 },
    "BB:1": { axis: "x" as const, pos: 99 },
  };

  it("moves the output keys with the rows and drops the deleted row's key", () => {
    const out = remapBranchWaypoints(wp, "B", { side: "output", map: remapDelete(3, 0) });
    expect(out).toEqual({
      "B:0": { axis: "x", pos: 11 },
      "B:1": { axis: "y", pos: 12 },
      "B:9": { axis: "y", pos: 19 },
      "BB:1": { axis: "x", pos: 99 },
    });
  });

  it("swaps keys for ↑/↓", () => {
    const out = remapBranchWaypoints(wp, "B", { side: "output", map: remapSwap(3, 1, 2) });
    expect(out["B:1"]).toEqual({ axis: "y", pos: 12 });
    expect(out["B:2"]).toEqual({ axis: "x", pos: 11 });
  });

  it("ignores input remaps and identity maps", () => {
    expect(remapBranchWaypoints(wp, "B", { side: "input", map: remapDelete(3, 0) })).toBe(wp);
    expect(remapBranchWaypoints(wp, "B", { side: "output", map: remapAppend(3) })).toBe(wp);
  });
});

describe("parseTextList / formatTextList", () => {
  it("trims lines and drops blank ones (D7)", () => {
    expect(parseTextList("  a: x \r\n\n   \nb: y\rc")).toEqual(["a: x", "b: y", "c"]);
    expect(parseTextList("")).toEqual([]);
  });

  it("round-trips rows one per line", () => {
    expect(parseTextList(formatTextList(["a", "b c"]))).toEqual(["a", "b c"]);
  });
});

describe("displayRows", () => {
  const result: ParamRowsDescribeResponse = {
    columns: ["name", "part"],
    rows: [
      { cells: ["a", "bolt"], error: null },
      { cells: ["b", "nut"], error: "bad" },
      { cells: ["c", "pin"], error: null },
    ],
    ports: "input",
  };

  it("shows raw rows when nothing is described yet", () => {
    expect(displayRows(["a", "b"], null)).toEqual({
      columns: null,
      rows: [
        { cells: ["a"], error: null, dim: false },
        { cells: ["b"], error: null, dim: false },
      ],
    });
  });

  it("matches by position when the described rows are the current rows", () => {
    const shown = displayRows(["a", "b", "c"], { requestRows: ["a", "b", "c"], result });
    expect(shown.columns).toEqual(["name", "part"]);
    expect(shown.rows[1]).toEqual({ cells: ["b", "nut"], error: "bad", dim: false });
  });

  it("matches by text after an edit and dims rows that are not described yet", () => {
    // 途中の行を消した直後: 番号でずらして当てない
    const shown = displayRows(["a", "c", "new"], { requestRows: ["a", "b", "c"], result });
    expect(shown.rows).toEqual([
      { cells: ["a", "bolt"], error: null, dim: false },
      { cells: ["c", "pin"], error: null, dim: false },
      { cells: ["new", null], error: null, dim: true },
    ]);
  });
});

describe("fieldValuesFor", () => {
  const variant: ParamRowsVariant = {
    id: "group",
    label: "Group",
    fields: [
      { key: "name", label: "Name", kind: "text" },
      {
        key: "mode",
        label: "Mode",
        kind: "choice",
        options: [
          { value: "rate", label: "Rate" },
          { value: "spike", label: "Spike" },
        ],
      },
      { key: "parts", label: "Parts", kind: "pick" },
    ],
  };

  it("fills defaults for missing values", () => {
    expect(fieldValuesFor(variant)).toEqual({ name: "", mode: "rate", parts: [] });
  });

  it("keeps valid given values and drops unknown keys and bad choices", () => {
    expect(
      fieldValuesFor(variant, { name: "x", mode: "spike", parts: ["a"], extra: "?" }),
    ).toEqual({ name: "x", mode: "spike", parts: ["a"] });
    expect(fieldValuesFor(variant, { mode: "nope", name: ["x"] }).mode).toBe("rate");
  });

  it("caps pick values", () => {
    const many = Array.from({ length: MAX_PICK_VALUES + 5 }, (_, i) => `p${i}`);
    expect((fieldValuesFor(variant, { parts: many }).parts as string[]).length).toBe(
      MAX_PICK_VALUES,
    );
  });
});
