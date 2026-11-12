// キャンバスのブロック上での右ボタン操作の状態機械 (lib/rightButtonGesture.ts)。
// 右ドラッグ = 複製、動かさず離す = コンテキストメニュー、を取り違えないことを固定する。

import { beforeEach, describe, expect, it } from "vitest";

import {
  RIGHT_DRAG_THRESHOLD_PX,
  createRightButtonGesture,
  type GesturePointerEvent,
  type RightButtonGesture,
  type ScreenPoint,
} from "../src/lib/rightButtonGesture";
import type { BlockEntry } from "../src/types/api";

const SUBSYSTEM = "flode.subsystems.subsystem.Subsystem";
const GAIN = "flode.blocks.mathops.Gain";
const PROVENANCE = { library: "user", library_uid: "uid-1", entry: "pid", revision: 2 };

/** host の代役: ブロック一覧・位置・選択・開いたメニュー・複製中フラグを記録する。 */
interface FakeWorld {
  blocks: BlockEntry[];
  positions: Record<string, { x: number; y: number }>;
  selected: string[];
  menus: Array<{ at: ScreenPoint; block: BlockEntry }>;
  copying: boolean;
  zoom: number;
  gesture: RightButtonGesture;
}

function createWorld(): FakeWorld {
  const world: FakeWorld = {
    blocks: [
      {
        id: "sub",
        type: SUBSYSTEM,
        params: { blocks: [], connections: [], nested: { k: 1 } },
        provenance: PROVENANCE,
      },
      { id: "g", type: GAIN, params: { k: 2 } },
    ],
    positions: { sub: { x: 100, y: 50 }, g: { x: 300, y: 50 } },
    selected: [],
    menus: [],
    copying: false,
    zoom: 1,
    gesture: undefined as unknown as RightButtonGesture,
  };
  world.gesture = createRightButtonGesture({
    findBlock: (id) => {
      const block = world.blocks.find((b) => b.id === id);
      if (!block) return null;
      return {
        block,
        pos: world.positions[id] ?? { x: 0, y: 0 },
        ids: new Set(world.blocks.map((b) => b.id)),
      };
    },
    addBlock: (block, pos) => {
      world.blocks.push(block);
      world.positions[block.id] = pos;
    },
    moveBlock: (id, pos) => {
      world.positions[id] = pos;
    },
    getZoom: () => world.zoom,
    getSelectedIds: () => world.selected,
    select: (id) => {
      world.selected = [id];
    },
    openMenu: (at, block) => world.menus.push({ at, block }),
    setCopying: (active) => {
      world.copying = active;
    },
  });
  return world;
}

/** 右ボタン押下中のイベント。 */
function right(clientX: number, clientY: number): GesturePointerEvent {
  return { button: 2, buttons: 2, clientX, clientY };
}

let w: FakeWorld;
beforeEach(() => {
  w = createWorld();
});

describe("right click (no drag) opens the menu", () => {
  it("moving less than the threshold and releasing creates no copy and opens the menu", () => {
    expect(w.gesture.down(right(10, 10), "sub")).toBe(true);
    w.gesture.move(right(10 + RIGHT_DRAG_THRESHOLD_PX - 1, 10));
    w.gesture.up(right(13, 10));
    expect(w.blocks).toHaveLength(2);
    expect(w.copying).toBe(false);
    expect(w.menus).toHaveLength(1);
    expect(w.menus[0]?.at).toEqual({ x: 13, y: 10 });
    expect(w.menus[0]?.block.id).toBe("sub");
    expect(w.selected).toEqual(["sub"]);
  });

  it("does not open a menu for block types that cannot be registered, but still selects", () => {
    w.gesture.down(right(0, 0), "g");
    w.gesture.up(right(0, 0));
    expect(w.menus).toHaveLength(0);
    expect(w.selected).toEqual(["g"]);
    expect(w.blocks).toHaveLength(2);
  });

  it("keeps a multi-selection when the clicked block is part of it", () => {
    w.selected = ["sub", "g"];
    w.gesture.down(right(0, 0), "sub");
    w.gesture.up(right(0, 0));
    expect(w.selected).toEqual(["sub", "g"]);
    expect(w.menus).toHaveLength(1);
  });

  it("selects only the clicked block when it is outside the current selection", () => {
    w.selected = ["g"];
    w.gesture.down(right(0, 0), "sub");
    w.gesture.up(right(0, 0));
    expect(w.selected).toEqual(["sub"]);
  });

  it("ignores non-right buttons and unknown blocks on mousedown", () => {
    expect(w.gesture.down({ button: 0, buttons: 1, clientX: 0, clientY: 0 }, "sub")).toBe(false);
    expect(w.gesture.down(right(0, 0), "missing")).toBe(false);
    w.gesture.up(right(0, 0));
    expect(w.menus).toHaveLength(0);
  });
});

describe("right drag copies the block", () => {
  it("creates exactly one copy at the threshold, with a unique id, provenance and cloned params", () => {
    w.gesture.down(right(10, 10), "sub");
    w.gesture.move(right(10 + RIGHT_DRAG_THRESHOLD_PX, 10));
    w.gesture.move(right(40, 30));
    w.gesture.move(right(60, 50));
    expect(w.blocks).toHaveLength(3);
    expect(w.copying).toBe(true);
    const copy = w.blocks[2]!;
    expect(copy.id).not.toBe("sub");
    expect(new Set(w.blocks.map((b) => b.id)).size).toBe(3);
    expect(copy.type).toBe(SUBSYSTEM);
    // 由来は引き継ぐ (ADR-0080 §A3-4)
    expect(copy.provenance).toEqual(PROVENANCE);
    // params は同じ内容の別参照 (入れ子も)
    expect(copy.params).toEqual(w.blocks[0]!.params);
    expect(copy.params).not.toBe(w.blocks[0]!.params);
    expect(copy.params.nested).not.toBe(w.blocks[0]!.params.nested);
    // 複製はカーソルに追従し、元のブロックは動かない
    expect(w.positions[copy.id]).toEqual({ x: 150, y: 90 });
    expect(w.positions.sub).toEqual({ x: 100, y: 50 });

    w.gesture.up(right(60, 50));
    expect(w.copying).toBe(false);
    expect(w.selected).toEqual([copy.id]);
    expect(w.menus).toHaveLength(0);
    expect(w.blocks).toHaveLength(3);
  });

  it("does not add a provenance key when the source has none", () => {
    w.gesture.down(right(0, 0), "g");
    w.gesture.move(right(20, 0));
    expect(w.blocks[2]).not.toHaveProperty("provenance");
  });

  it("converts screen movement to canvas coordinates with the zoom factor", () => {
    w.zoom = 2;
    w.gesture.down(right(0, 0), "sub");
    w.gesture.move(right(40, 20));
    expect(w.positions[w.blocks[2]!.id]).toEqual({ x: 120, y: 60 });
  });
});

describe("lost mouseup (button released outside the window)", () => {
  it("a mouseup of another button is ignored", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.up({ button: 0, buttons: 2, clientX: 0, clientY: 0 });
    expect(w.menus).toHaveLength(0);
    // 右ボタンの mouseup で初めて確定する
    w.gesture.up(right(0, 0));
    expect(w.menus).toHaveLength(1);
  });

  it("a mousemove without the right button cancels before any copy is made", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.move({ button: 0, buttons: 0, clientX: 200, clientY: 200 });
    w.gesture.move({ button: 0, buttons: 0, clientX: 300, clientY: 300 });
    expect(w.blocks).toHaveLength(2);
    expect(w.copying).toBe(false);
    // 取り消されたので、その後の mouseup でメニューも開かない
    w.gesture.up(right(300, 300));
    expect(w.menus).toHaveLength(0);
  });

  it("a mousemove without the right button stops an ongoing copy from following the cursor", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.move(right(20, 0));
    const copy = w.blocks[2]!;
    const placed = { ...w.positions[copy.id]! };
    w.gesture.move({ button: 0, buttons: 0, clientX: 500, clientY: 500 });
    w.gesture.move({ button: 0, buttons: 1, clientX: 600, clientY: 600 });
    expect(w.positions[copy.id]).toEqual(placed);
    expect(w.copying).toBe(false);
    expect(w.selected).toEqual([copy.id]);
    expect(w.blocks).toHaveLength(3);
  });

  it("window blur cancels the same way", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.move(right(20, 0));
    w.gesture.cancel();
    expect(w.copying).toBe(false);
    w.gesture.move(right(400, 400));
    expect(w.blocks).toHaveLength(3);
    expect(w.positions[w.blocks[2]!.id]).toEqual({ x: 120, y: 50 });
  });
});

describe("contextmenu event (keyboard / touch)", () => {
  it("opens the menu when no mouse press preceded it", () => {
    w.gesture.contextMenu("sub", { x: 5, y: 6 });
    expect(w.menus).toEqual([{ at: { x: 5, y: 6 }, block: w.blocks[0] }]);
    expect(w.selected).toEqual(["sub"]);
  });

  it("does not open a second menu for the contextmenu that follows a mouse right click", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.up(right(0, 0));
    w.gesture.contextMenu("sub", { x: 0, y: 0 });
    expect(w.menus).toHaveLength(1);
    // その次の (キーボード起点の) contextmenu は開く
    w.gesture.contextMenu("sub", { x: 1, y: 1 });
    expect(w.menus).toHaveLength(2);
  });

  it("also swallows it when contextmenu arrives before mouseup (other platforms)", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.contextMenu("sub", { x: 0, y: 0 });
    expect(w.menus).toHaveLength(0);
    w.gesture.up(right(0, 0));
    expect(w.menus).toHaveLength(1);
  });

  it("a contextmenu outside any block clears the pending mouse flag without opening", () => {
    w.gesture.down(right(0, 0), "sub");
    w.gesture.move(right(50, 0));
    w.gesture.up(right(50, 0));
    w.gesture.contextMenu(null, { x: 50, y: 0 });
    expect(w.menus).toHaveLength(0);
    w.gesture.contextMenu("sub", { x: 2, y: 2 });
    expect(w.menus).toHaveLength(1);
  });

  it("does not open for block types that cannot be registered", () => {
    w.gesture.contextMenu("g", { x: 0, y: 0 });
    expect(w.menus).toHaveLength(0);
  });
});
