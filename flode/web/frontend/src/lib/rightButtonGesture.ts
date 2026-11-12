// キャンバスのブロック上での右ボタン操作の状態機械 (SPEC-0032 §1.2 / ADR-0080)。
//
// - 押したまま閾値以上動かす → ブロックを複製し、複製がカーソルに追従する
// - 動かさずに離す (= 右クリック) → コンテキストメニュー
// - キーボード (ContextMenu キー / Shift+F10) やタッチ長押しは mousedown を伴わず
//   ``contextmenu`` イベントだけが来る → 同じメニューを開く
//
// DOM / store には直接触らず、必要な操作は ``RightButtonGestureHost`` 経由で行う
// (= 状態遷移を unit test できるようにする)。イベントの配線は DiagramCanvas が持つ。

import type { BlockEntry } from "../types/api";
import { generateUniqueId } from "./idGenerator";
import { isRegistrableBlockType } from "./libraryProvenance";

/**
 * 右ボタンを押したままこの距離 (px) 以上動かしたら「複製ドラッグ」、それ未満で
 * 離したら「右クリック」(= コンテキストメニュー) とみなす。
 */
export const RIGHT_DRAG_THRESHOLD_PX = 4;

/** ``MouseEvent.button`` の右ボタン。 */
const RIGHT_BUTTON = 2;
/** ``MouseEvent.buttons`` の右ボタンのビット。 */
const RIGHT_BUTTONS_MASK = 2;

/** 画面上の位置 (viewport 座標)。 */
export interface ScreenPoint {
  x: number;
  y: number;
}

/** 現在の階層にあるブロック 1 つの情報。 */
export interface GestureBlockInfo {
  block: BlockEntry;
  /** キャンバス (flow) 座標での位置。 */
  pos: { x: number; y: number };
  /** 同じ階層の既存 block id (複製の id 採番用)。 */
  ids: ReadonlySet<string>;
}

/** 状態機械が外界に対して行う操作。 */
export interface RightButtonGestureHost {
  /** 現在の階層から ``id`` のブロックを探す (無ければ null)。 */
  findBlock: (id: string) => GestureBlockInfo | null;
  /** ブロックを現在の階層に追加する。 */
  addBlock: (block: BlockEntry, pos: { x: number; y: number }) => void;
  /** ブロックを flow 座標 ``pos`` に動かす。 */
  moveBlock: (id: string, pos: { x: number; y: number }) => void;
  /** 現在のズーム倍率 (画面上の移動量を flow 座標に直す)。 */
  getZoom: () => number;
  /** 選択中の block id。 */
  getSelectedIds: () => readonly string[];
  /** ``id`` だけを選択する。 */
  select: (id: string) => void;
  /** ブロックのコンテキストメニューを ``at`` に開く。 */
  openMenu: (at: ScreenPoint, block: BlockEntry) => void;
  /** 複製ドラッグ中かどうかを通知する (追従中の CSS transition 無効化用)。 */
  setCopying: (active: boolean) => void;
}

/** 状態機械が見るマウスイベントの部分。 */
export interface GesturePointerEvent {
  button: number;
  buttons: number;
  clientX: number;
  clientY: number;
}

/** 右ボタン操作の状態機械。DOM イベントから対応するメソッドを呼ぶ。 */
export interface RightButtonGesture {
  /**
   * ブロック ``nodeId`` 上の mousedown。
   * @returns 右ボタン操作として引き受けたか (true なら呼び出し側で既定動作を止める)。
   */
  down: (e: GesturePointerEvent, nodeId: string) => boolean;
  /** window の mousemove。 */
  move: (e: GesturePointerEvent) => void;
  /** window の mouseup。 */
  up: (e: GesturePointerEvent) => void;
  /** 進行中の操作を打ち切る (window の blur、unmount)。 */
  cancel: () => void;
  /**
   * ``contextmenu`` イベント。マウスの右クリックに伴うものは無視し (メニューは
   * mouseup 側で開く)、キーボード / タッチ起点のものだけメニューを開く。
   *
   * @param nodeId 対象ブロック (イベント対象がブロックでなければ null)。
   * @param at メニューを開く位置。
   */
  contextMenu: (nodeId: string | null, at: ScreenPoint) => void;
}

/**
 * 右ボタン操作の状態機械を作る。
 *
 * @param host 外界への操作 (store / DOM / React state)。
 */
export function createRightButtonGesture(host: RightButtonGestureHost): RightButtonGesture {
  // 右ボタン押下中の状態。``newId`` が null の間はまだ複製していない (= 閾値未満)。
  let drag: {
    origId: string;
    newId: string | null;
    start: ScreenPoint;
    origin: { x: number; y: number };
  } | null = null;
  // マウスの右ボタン押下に伴う contextmenu イベントを 1 回だけ読み飛ばすための印。
  // (contextmenu は OS により mousedown 直後または mouseup 直後に来る)
  let mouseContextMenuPending = false;

  /** 右クリック / キーボード起点の共通処理: 選択を整えてメニューを開く。 */
  const showMenu = (id: string, at: ScreenPoint): void => {
    const found = host.findBlock(id);
    if (!found) return;
    // 複数選択に含まれるブロックなら選択を保つ。含まれなければそのブロックだけ選択
    if (!host.getSelectedIds().includes(id)) host.select(id);
    // SPEC-0032 §1.2-1: 登録できない種別では項目を出さない (= メニュー自体を開かない)
    if (isRegistrableBlockType(found.block.type)) host.openMenu(at, found.block);
  };

  /** 進行中の操作を終える。複製済みなら複製を選択して確定する。 */
  const finish = (): void => {
    const current = drag;
    drag = null;
    if (current === null || current.newId === null) return;
    host.setCopying(false);
    // 複製を選択状態にして、そのまま左ドラッグで微調整できるようにする
    host.select(current.newId);
  };

  return {
    down(e, nodeId) {
      if (e.button !== RIGHT_BUTTON) return false;
      const found = host.findBlock(nodeId);
      if (!found) return false;
      // 前の操作が mouseup を取りこぼしたまま残っていたら確定してから始める
      finish();
      // 複製は閾値を超えて動かしたときに初めて行う (単なる右クリックで重なった
      // 複製ができないようにする)
      drag = {
        origId: nodeId,
        newId: null,
        start: { x: e.clientX, y: e.clientY },
        origin: { x: found.pos.x, y: found.pos.y },
      };
      mouseContextMenuPending = true;
      return true;
    },

    move(e) {
      if (drag === null) return;
      // 右ボタンがもう押されていない = mouseup を取りこぼした (押したまま Alt+Tab 等)。
      // ここで打ち切らないと、戻ってきて動かしただけで複製ができ、追従し続ける
      if ((e.buttons & RIGHT_BUTTONS_MASK) === 0) {
        mouseContextMenuPending = false;
        finish();
        return;
      }
      const dx = e.clientX - drag.start.x;
      const dy = e.clientY - drag.start.y;
      if (drag.newId === null) {
        if (Math.hypot(dx, dy) < RIGHT_DRAG_THRESHOLD_PX) return;
        const found = host.findBlock(drag.origId);
        if (!found) {
          drag = null;
          return;
        }
        // id を新しく採番し、パラメータは deep copy する (同じ参照だと後の編集が
        // 双方に反映される)。それ以外のキー (由来 ``provenance`` 等) は spread で
        // 引き継ぐ (ADR-0080 §A3-4: 複製も同じエントリ由来の部品)。
        const newId = generateUniqueId(found.block.type, found.ids);
        host.addBlock(
          {
            ...found.block,
            id: newId,
            params: JSON.parse(JSON.stringify(found.block.params)) as Record<string, unknown>,
          },
          found.pos,
        );
        host.setCopying(true);
        drag.newId = newId;
      }
      const zoom = host.getZoom() || 1;
      host.moveBlock(drag.newId, {
        x: drag.origin.x + dx / zoom,
        y: drag.origin.y + dy / zoom,
      });
    },

    up(e) {
      if (drag === null || e.button !== RIGHT_BUTTON) return;
      if (drag.newId !== null) {
        finish();
        return;
      }
      // 動かさずに離した = 右クリック
      const { origId } = drag;
      drag = null;
      showMenu(origId, { x: e.clientX, y: e.clientY });
    },

    cancel() {
      mouseContextMenuPending = false;
      finish();
    },

    contextMenu(nodeId, at) {
      if (mouseContextMenuPending) {
        // マウスの右クリックに伴う contextmenu。メニューは mouseup 側で開く
        mouseContextMenuPending = false;
        return;
      }
      if (nodeId !== null) showMenu(nodeId, at);
    },
  };
}
