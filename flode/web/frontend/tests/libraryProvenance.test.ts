// SPEC-0032 §1.4 / ADR-0080 §A3・§Q8: ライブラリ由来 (provenance) の付与と、
// エントリ名由来の block id 採番。
//
// - drop: 詳細レスポンスから由来を作る (uid が無ければキーごと省略)、id は表示名由来
// - 登録元への由来付与: applyEditingModel 1 回 = undo 1 回で戻り、dirty になる
// - コピー / 貼り付けで由来が引き継がれる

import { beforeEach, describe, expect, it } from "vitest";

import { generateIdFromName } from "../src/lib/idGenerator";
import {
  blockFromLibraryEntry,
  buildProvenance,
  isRegistrableBlockType,
} from "../src/lib/libraryProvenance";
import {
  copySelectionToClipboard,
  pasteClipboard,
  setBlockProvenanceInEditing,
  useAppStore,
} from "../src/store/appStore";
import type { FlwModel, LibraryEntryDetail } from "../src/types/api";

const SUBSYSTEM = "flode.subsystems.subsystem.Subsystem";
const PYTHON_FUNCTION = "flode.blocks.pythonfunc.PythonFunction";

function detail(overrides: Partial<LibraryEntryDetail> = {}): LibraryEntryDetail {
  return {
    id: "pid",
    display_name: "PID",
    display_name_i18n: {},
    description: "",
    description_i18n: {},
    category_suffix: "",
    kind: "subsystem",
    revision: 3,
    updated_at: "2026-11-12T10:00:00Z",
    contains_python: false,
    python_block_paths: [],
    library_uid: "8c1e2f0a-0000-4000-8000-000000000000",
    block: { id: "PID", type: SUBSYSTEM, params: { blocks: [], connections: [] } },
    ...overrides,
  };
}

function model(): FlwModel {
  return {
    schema_version: "0.15",
    simulator: { t_end: 1, dt: 0.1, solver: "RK45", rtol: 1e-6, atol: 1e-8, dt_base: null },
    blocks: [
      { id: "sub", type: SUBSYSTEM, params: { blocks: [{ id: "inner", type: SUBSYSTEM, params: { blocks: [], connections: [] } }], connections: [] } },
      { id: "g", type: "flode.blocks.mathops.Gain", params: { k: 2 } },
    ],
    connections: [],
    layout: { sub: { x: 0, y: 0 }, g: { x: 100, y: 0 } },
  };
}

beforeEach(() => {
  useAppStore.getState().setEditingModel(model());
  useAppStore.setState({ editingPath: [], dirty: false, selectedNodeIds: [], clipboard: null });
});

describe("generateIdFromName (entry-name-derived block id)", () => {
  it("uses the display name as is when it is a valid id", () => {
    expect(generateIdFromName("PID", SUBSYSTEM, new Set())).toBe("PID");
    expect(generateIdFromName("速度制御", SUBSYSTEM, new Set())).toBe("速度制御");
  });

  it("replaces characters that are not allowed in a block id with _", () => {
    expect(generateIdFromName("PID Controller", SUBSYSTEM, new Set())).toBe("PID_Controller");
    // 連続する _ は 1 つに畳み、末尾の _ は削る
    expect(generateIdFromName("  low-pass (2nd) ", SUBSYSTEM, new Set())).toBe("low_pass_2nd");
    expect(generateIdFromName("my__name", SUBSYSTEM, new Set())).toBe("my_name");
    expect(generateIdFromName("(lead) filter", SUBSYSTEM, new Set())).toBe("_lead_filter");
    expect(generateIdFromName("摩擦🔥モデル", SUBSYSTEM, new Set())).toBe("摩擦_モデル");
  });

  it("appends _2, _3 … on collision (including confusable duplicates)", () => {
    expect(generateIdFromName("PID", SUBSYSTEM, new Set(["PID"]))).toBe("PID_2");
    expect(generateIdFromName("PID", SUBSYSTEM, new Set(["PID", "PID_2"]))).toBe("PID_3");
    // 全角の「ＰＩＤ」は NFKC fold で PID と衝突する
    expect(generateIdFromName("PID", SUBSYSTEM, new Set(["ＰＩＤ"]))).toBe("PID_2");
  });

  it("falls back to the type-derived id when the name cannot become a valid id", () => {
    // 数字始まり・記号だけ・空・長すぎる名前
    expect(generateIdFromName("2nd order", SUBSYSTEM, new Set())).toBe("Subsystem_0");
    expect(generateIdFromName("★★★", SUBSYSTEM, new Set())).toBe("Subsystem_0");
    expect(generateIdFromName("   ", PYTHON_FUNCTION, new Set())).toBe("PythonFunction_0");
    expect(generateIdFromName("a".repeat(65), SUBSYSTEM, new Set(["Subsystem_0"]))).toBe(
      "Subsystem_1",
    );
  });
});

describe("blockFromLibraryEntry (drop)", () => {
  it("builds provenance from the detail response and a name-derived id", () => {
    const placed = blockFromLibraryEntry("user", detail(), new Set(["PID"]));
    expect(placed).toEqual({
      id: "PID_2",
      type: SUBSYSTEM,
      params: { blocks: [], connections: [] },
      provenance: {
        library: "user",
        library_uid: "8c1e2f0a-0000-4000-8000-000000000000",
        entry: "pid",
        revision: 3,
      },
    });
  });

  it("omits library_uid entirely for libraries without a uid", () => {
    const placed = blockFromLibraryEntry("std", detail({ library_uid: null }), new Set());
    expect(placed.provenance).toEqual({ library: "std", entry: "pid", revision: 3 });
    expect(Object.keys(placed.provenance ?? {})).not.toContain("library_uid");
    // JSON にも null / 空文字として出ない
    expect(JSON.stringify(placed)).not.toContain("library_uid");
  });

  it("keeps the body params by reference (byte-identical placement)", () => {
    const d = detail();
    expect(blockFromLibraryEntry("user", d, new Set()).params).toBe(d.block.params);
  });

  it("places a PythonFunction entry as a PythonFunction (not wrapped)", () => {
    const d = detail({
      display_name: "Friction Model",
      kind: "python_function",
      block: { id: "f", type: PYTHON_FUNCTION, params: { code: "x" } },
    });
    const placed = blockFromLibraryEntry("user", d, new Set());
    expect(placed.type).toBe(PYTHON_FUNCTION);
    expect(placed.id).toBe("Friction_Model");
  });
});

describe("isRegistrableBlockType", () => {
  it("accepts only Subsystem and PythonFunction", () => {
    expect(isRegistrableBlockType(SUBSYSTEM)).toBe(true);
    expect(isRegistrableBlockType(PYTHON_FUNCTION)).toBe(true);
    expect(isRegistrableBlockType("flode.blocks.mathops.Gain")).toBe(false);
  });
});

describe("setBlockProvenanceInEditing (registration source)", () => {
  const prov = buildProvenance("user", "uid-1", "pid", 1);

  it("attaches provenance, marks dirty, and one undo restores the model", () => {
    const before = useAppStore.getState().editingModel;
    setBlockProvenanceInEditing([], "sub", prov);
    const state = useAppStore.getState();
    expect(state.editingModel?.blocks[0]?.provenance).toEqual(prov);
    expect(state.editingModel?.blocks[1]?.provenance).toBeUndefined();
    expect(state.dirty).toBe(true);
    expect(state.history.past).toHaveLength(1);

    state.undo();
    expect(useAppStore.getState().editingModel).toEqual(before);
    expect(useAppStore.getState().editingModel?.blocks[0]).not.toHaveProperty("provenance");
  });

  it("targets the block at the given path, not the current path", () => {
    setBlockProvenanceInEditing(["sub"], "inner", prov);
    const sub = useAppStore.getState().editingModel?.blocks[0];
    const inner = (sub?.params.blocks as Array<{ id: string; provenance?: unknown }>)[0];
    expect(inner?.provenance).toEqual(prov);
    expect(sub?.provenance).toBeUndefined();
  });

  it("does nothing when the block or the path no longer exists", () => {
    setBlockProvenanceInEditing([], "gone", prov);
    setBlockProvenanceInEditing(["nope"], "inner", prov);
    const state = useAppStore.getState();
    expect(state.history.past).toHaveLength(0);
    expect(state.dirty).toBe(false);
  });
});

describe("copy / paste keeps provenance", () => {
  it("pasted blocks carry the same provenance as the source", () => {
    const prov = buildProvenance("user", "uid-1", "pid", 2);
    setBlockProvenanceInEditing([], "sub", prov);
    useAppStore.getState().setSelectedNodeIds(["sub", "g"]);
    copySelectionToClipboard();
    pasteClipboard();
    const blocks = useAppStore.getState().editingModel?.blocks ?? [];
    expect(blocks).toHaveLength(4);
    const pastedSub = blocks[2];
    expect(pastedSub?.id).not.toBe("sub");
    expect(pastedSub?.provenance).toEqual(prov);
    // 由来の無いブロックの複製にはキーが現れない
    expect(blocks[3]).not.toHaveProperty("provenance");
  });
});
