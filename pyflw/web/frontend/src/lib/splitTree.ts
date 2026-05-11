// ADR-0045 §(2) / §(3-D): Workspace JupyterLab Stage 1 の split tree データ構造と
// 純関数。SplitTree は LeafNode (= 単一 pane) と SplitNode (= 縦/横分割) の
// 再帰的構造で、Diagram + Scope 群を `<main>` 内に任意配置するための骨格。
//
// **永続化**: モデル別、key 形式 `pyflw.workspace_layout.<hash>.<b64url(path)>`
// (= storageKeys.makeWorkspaceLayoutKey)。値は ``serializeTree`` の出力。
//
// **paneId の semantics** (= ADR-0045 §(2)):
// - "diagram"          = 唯一の Diagram pane (= 1 モデルに 1 個固定)
// - "scope:<scopeId>"  = 特定 Scope ブロック 1 個分の pane
// - "scopes-stack"     = 未分離 Scope を縦並べで束ねた pane (= Stage 1 fallback)

/** 葉 = 単一 pane を表す。 */
export interface LeafNode {
  kind: "leaf";
  paneId: string;
}

/** 内部ノード = 縦/横 split。
 *
 * - ``orientation: "horizontal"`` = 左右分割 (a = 左、b = 右)
 * - ``orientation: "vertical"``   = 上下分割 (a = 上、b = 下)
 * - ``ratio`` は a 側の割合 (= 0 < ratio < 1)
 */
export interface SplitNode {
  kind: "split";
  orientation: "horizontal" | "vertical";
  ratio: number;
  a: SplitTree;
  b: SplitTree;
}

export type SplitTree = LeafNode | SplitNode;

/** 既定値 = Diagram pane 単独 (= Scope が無い / モデル新規時)。
 * **Object.freeze** で凍結 (= mutator 経由で誤って書き換える事故を防ぐ、
 * code-reviewer §MUST #2 指摘)。 */
export const DEFAULT_TREE: SplitTree = Object.freeze({
  kind: "leaf",
  paneId: "diagram",
}) as SplitTree;

/** ADR-0045 §(2) 最小構成 fallback: Diagram + scopes-stack の縦 60/40 split。
 * v3.5.x までの ``id="pyflw.scope_split"`` レイアウトと同等。本オブジェクトも
 * frozen。store action は **新規オブジェクト** を作って set するため shallow
 * freeze で十分 (= 内側の a / b は freeze で保護されているとは限らない点に注意、
 * 直接参照を mutate しないこと)。 */
export const DEFAULT_TREE_WITH_SCOPES: SplitTree = Object.freeze({
  kind: "split",
  orientation: "vertical",
  ratio: 0.6,
  a: Object.freeze({ kind: "leaf", paneId: "diagram" }) as LeafNode,
  b: Object.freeze({ kind: "leaf", paneId: "scopes-stack" }) as LeafNode,
}) as SplitTree;

/** clamp 用の安全 ratio 範囲 (= 端は十分に余白を残す)。
 *
 * **注意**: ``isValidRatio`` は **構造検証** で開区間 ``(0, 1)`` を許容するが、
 * ``clampRatio`` は **値正規化** で ``[MIN_RATIO, MAX_RATIO]`` に狭める。
 * 2 つの range が異なる理由は: deserialize 時に 0/1 ぴったりや NaN は不正 JSON
 * として弾くべき (= isValidRatio で構造 reject) だが、0.001 のような極端な値は
 * 構造的には valid なので受け入れて、後段の normalize で 0.05 にクランプする
 * (= UX 上 pane が見えなくなるのを防ぐ)。 */
const MIN_RATIO = 0.05;
const MAX_RATIO = 0.95;

/** ratio が finite かつ (0, 1) 開区間かを判定する **構造検証** (= deserialize で使用)。
 * 値の妥当性 (= [MIN_RATIO, MAX_RATIO] 範囲) は ``clampRatio`` / ``normalizeTree``
 * で保証する。 */
function isValidRatio(r: unknown): r is number {
  return typeof r === "number" && Number.isFinite(r) && r > 0 && r < 1;
}

/** ratio を ``[MIN_RATIO, MAX_RATIO]`` に clamp する **値正規化**。 */
function clampRatio(r: number): number {
  if (!Number.isFinite(r)) return 0.5;
  return Math.max(MIN_RATIO, Math.min(MAX_RATIO, r));
}

/** SplitTree 内のすべての葉 paneId をフラットに列挙 (深さ優先、a → b 順)。 */
export function getLeafPaneIds(tree: SplitTree): string[] {
  if (tree.kind === "leaf") return [tree.paneId];
  return [...getLeafPaneIds(tree.a), ...getLeafPaneIds(tree.b)];
}

/** SplitTree 内に特定 paneId の葉が存在するか。 */
export function findLeaf(tree: SplitTree, paneId: string): boolean {
  if (tree.kind === "leaf") return tree.paneId === paneId;
  return findLeaf(tree.a, paneId) || findLeaf(tree.b, paneId);
}

/** ``target`` 葉を split node に置き換える。
 *
 * @param tree         元の SplitTree (immutable、関数は新 tree を返す)
 * @param targetPaneId 分割する葉の paneId
 * @param orientation  "horizontal" = 左右分割、"vertical" = 上下分割
 * @param newPaneId    新規に追加する葉の paneId
 * @param position     "after" (= 既存葉が a 側、新葉が b 側 / 右 or 下) /
 *                     "before" (= 既存葉が b 側、新葉が a 側 / 左 or 上)
 * @returns 新 SplitTree。``targetPaneId`` が見つからない / ``newPaneId`` が
 *          既に存在する場合は変更せず元 tree を返す。
 */
export function insertSplit(
  tree: SplitTree,
  targetPaneId: string,
  orientation: "horizontal" | "vertical",
  newPaneId: string,
  position: "after" | "before" = "after",
): SplitTree {
  if (!findLeaf(tree, targetPaneId)) return tree;
  if (findLeaf(tree, newPaneId)) return tree;
  return insertSplitRecur(tree, targetPaneId, orientation, newPaneId, position);
}

function insertSplitRecur(
  tree: SplitTree,
  targetPaneId: string,
  orientation: "horizontal" | "vertical",
  newPaneId: string,
  position: "after" | "before",
): SplitTree {
  if (tree.kind === "leaf") {
    if (tree.paneId !== targetPaneId) return tree;
    const existing: LeafNode = { kind: "leaf", paneId: targetPaneId };
    const fresh: LeafNode = { kind: "leaf", paneId: newPaneId };
    return {
      kind: "split",
      orientation,
      ratio: 0.5,
      a: position === "after" ? existing : fresh,
      b: position === "after" ? fresh : existing,
    };
  }
  return {
    ...tree,
    a: insertSplitRecur(tree.a, targetPaneId, orientation, newPaneId, position),
    b: insertSplitRecur(tree.b, targetPaneId, orientation, newPaneId, position),
  };
}

/** ``target`` 葉を tree から除去。
 *
 * 兄弟が単一葉の場合は親 split node が縮約され、その葉が親の位置に昇格する。
 * tree 全体が 1 葉のみで構成され、その葉を除去する場合は ``null`` を返す
 * (= 呼び出し側で DEFAULT_TREE 等にフォールバックする)。
 */
export function removeLeaf(
  tree: SplitTree,
  targetPaneId: string,
): SplitTree | null {
  if (tree.kind === "leaf") {
    return tree.paneId === targetPaneId ? null : tree;
  }
  const aHas = findLeaf(tree.a, targetPaneId);
  const bHas = findLeaf(tree.b, targetPaneId);
  if (!aHas && !bHas) return tree;
  if (aHas) {
    const newA = removeLeaf(tree.a, targetPaneId);
    if (newA === null) return tree.b;
    return { ...tree, a: newA };
  }
  const newB = removeLeaf(tree.b, targetPaneId);
  if (newB === null) return tree.a;
  return { ...tree, b: newB };
}

/** 特定 split 葉の親 ratio を更新 (= drag resize 確定時)。
 *
 * Split node を一意に特定するため、subtree 内のすべての葉 paneId の集合
 * (= ``leafPath``) で識別する。完全一致した最初の split node の ratio を
 * 置き換える。
 */
export function setSplitRatio(
  tree: SplitTree,
  splitId: string,
  ratio: number,
): SplitTree {
  return mapSplitNodes(tree, (node, id) => {
    if (id !== splitId) return node;
    return { ...node, ratio: clampRatio(ratio) };
  });
}

/** 特定 split 葉の orientation を反転 (= 縦 ↔ 横 切替)。 */
export function toggleSplitOrientation(
  tree: SplitTree,
  splitId: string,
): SplitTree {
  return mapSplitNodes(tree, (node, id) => {
    if (id !== splitId) return node;
    return {
      ...node,
      orientation:
        node.orientation === "horizontal" ? "vertical" : "horizontal",
    };
  });
}

/** split node ごとに固有の ID を計算 (= subtree 内の全 leaf paneId を ``|`` で
 * 連結)。同型構造の split が複数あっても、保持する葉が異なれば ID が変わる。
 *
 * @internal
 */
export function makeSplitId(node: SplitNode): string {
  return `split:${getLeafPaneIds(node).join("|")}`;
}

function mapSplitNodes(
  tree: SplitTree,
  fn: (node: SplitNode, id: string) => SplitTree,
): SplitTree {
  if (tree.kind === "leaf") return tree;
  const id = makeSplitId(tree);
  const mapped = fn(tree, id);
  if (mapped !== tree) return mapped;
  return {
    ...tree,
    a: mapSplitNodes(tree.a, fn),
    b: mapSplitNodes(tree.b, fn),
  };
}

/** 不正な状態を正規化:
 * - ratio が範囲外なら clamp
 * - paneId が重複する葉があれば最初の出現以外を ``scopes-stack`` 統合扱いで除去
 *   (= 構造が破壊されていないことを保証)
 *
 * 葉が 1 つも残らない場合は ``null`` (= 呼び出し側で DEFAULT に fallback)。
 */
export function normalizeTree(tree: SplitTree): SplitTree | null {
  const seen = new Set<string>();
  return normalizeRecur(tree, seen);
}

function normalizeRecur(
  tree: SplitTree,
  seen: Set<string>,
): SplitTree | null {
  if (tree.kind === "leaf") {
    if (seen.has(tree.paneId)) return null;
    seen.add(tree.paneId);
    return tree;
  }
  const ratio = clampRatio(tree.ratio);
  const a = normalizeRecur(tree.a, seen);
  const b = normalizeRecur(tree.b, seen);
  if (a === null && b === null) return null;
  if (a === null) return b;
  if (b === null) return a;
  return { ...tree, ratio, a, b };
}

/** SplitTree を JSON 文字列にシリアライズ (= localStorage 保存形式)。 */
export function serializeTree(tree: SplitTree): string {
  return JSON.stringify(tree);
}

/** JSON 文字列を SplitTree にデシリアライズ。
 * パース失敗 / 構造不整合 / null 入力の場合は ``null`` を返す
 * (= 呼び出し側で DEFAULT_TREE 等にフォールバック)。
 */
export function deserializeTree(json: string | null | undefined): SplitTree | null {
  if (json === null || json === undefined || json === "") return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return null;
  }
  if (!isSplitTree(parsed)) return null;
  return normalizeTree(parsed);
}

function isSplitTree(value: unknown): value is SplitTree {
  if (typeof value !== "object" || value === null) return false;
  const obj = value as Record<string, unknown>;
  if (obj.kind === "leaf") {
    return typeof obj.paneId === "string" && obj.paneId.length > 0;
  }
  if (obj.kind === "split") {
    return (
      (obj.orientation === "horizontal" || obj.orientation === "vertical") &&
      isValidRatio(obj.ratio) &&
      isSplitTree(obj.a) &&
      isSplitTree(obj.b)
    );
  }
  return false;
}

/** ADR-0045 §(3-D): 旧 localStorage キー ``pyflw.scope_split`` (= v3.5.x の
 * ``react-resizable-panels`` autosave 想定値) から SplitTree への片方向 migration。
 *
 * 旧キーは ``react-resizable-panels`` の ``autoSaveId`` 経由でないと実際には
 * 保存されないため、現実には存在しないケースが大半。本関数は **存在を検知
 * したら DEFAULT_TREE_WITH_SCOPES (= 縦 60/40) で代用** する保守的な実装と
 * する (= 旧 ratio を厳密に復元するより、構造を確実に新形式に切替する優先)。
 *
 * 旧キーは **削除しない** (= ロールバックで v3.5.x に戻った時に動作する
 * ように、ADR-0043 §論点 8-D の慣例継承)。
 *
 * @param legacy 旧キー ``pyflw.scope_split`` の raw 値 (= localStorage.getItem の結果)
 * @returns 旧キーが存在し読めれば DEFAULT_TREE_WITH_SCOPES、存在しないか
 *          壊れていれば ``null``
 */
export function migrateFromScopeSplit(
  legacy: string | null | undefined,
): SplitTree | null {
  if (legacy === null || legacy === undefined || legacy === "") return null;
  return DEFAULT_TREE_WITH_SCOPES;
}

/** ADR-0045 §(2) §3-C: モデル切替時の SplitTree 初期化ロジック。
 *
 * 1. ``stored`` (= 新キーから読んだ JSON) が valid SplitTree なら復元
 * 2. ``legacy`` (= 旧 ``pyflw.scope_split``) が存在すれば ``DEFAULT_TREE_WITH_SCOPES``
 * 3. それ以外は visibleScopeCount に応じて ``DEFAULT_TREE`` か ``DEFAULT_TREE_WITH_SCOPES``
 *
 * @param stored             新 key (= ``pyflw.workspace_layout.*``) から読んだ raw JSON
 * @param legacy             旧 key (= ``pyflw.scope_split``) の raw 値
 * @param hasVisibleScopes   現モデルに描画対象 Scope が 1 個以上あるか
 */
export function chooseInitialTree(
  stored: string | null | undefined,
  legacy: string | null | undefined,
  hasVisibleScopes: boolean,
): SplitTree {
  const restored = deserializeTree(stored);
  if (restored !== null) return restored;
  const migrated = migrateFromScopeSplit(legacy);
  if (migrated !== null) return migrated;
  return hasVisibleScopes ? DEFAULT_TREE_WITH_SCOPES : DEFAULT_TREE;
}
