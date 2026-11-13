// ADR-0019 §(3) + UI 刷新: ブロックパレット。
// 各エントリに block 種別固有の SVG glyph プレビューを表示する Library
// Browser 風の見た目。検索 + カテゴリ折りたたみ。drag-start で
// `application/flode-block-type` を data transfer に積む。
//
// ADR-0029: マスク Subsystem 集合を配布する `.flwlib.json` (= block library) を
// Block class registry の **下** に Libraries セクションとして表示する。drag-start
// では `application/flode-library-entry-ref` MIME で `{library, entry}` を運び、
// drop 経路 (DiagramCanvas) で個別 fetch + Inline 展開する。
//
// ADR-0081 §8-B: Python で書いたユーザーブロックを、読み込み元ごとのセクション
// (ワークスペース → dirs → modules) として組み込みカテゴリより **上** に出す。
// 検索欄横の ⋯ メニュー・セクション見出しの右クリック・最下部のボタンから
// 「再読み込み」、最下部に読み込みエラー欄。並びの規則は ``lib/userBlocks.ts``。

import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listBlockMetadata, listLibraries } from "../api/client";
import { BlockGlyph } from "../lib/blockGlyphs";
import {
  localizeName,
  localizedDisplayName,
  localizedDocstringSummary,
  searchableDisplayNames,
} from "../lib/blockI18n";
import { cleanServerText, MAX_LABEL_CHARS, MAX_MESSAGE_CHARS } from "../lib/untrustedText";
import { BLOCKS_REGISTRY_QUERY_KEY } from "../lib/queryKeys";
import { useBlockReload } from "../lib/useBlockReload";
import { buildPaletteLayout, isUserBlock } from "../lib/userBlocks";
import type {
  BlockMetadata,
  BlockSourceInfo,
  LibraryEntryMetadata,
  LibraryMetadata,
} from "../types/api";
import { LoadErrorsPanel } from "./palette/LoadErrorsPanel";
import {
  BlockTile,
  CategoryHeader,
  TILE_CLS,
  TILE_GLYPH_CLS,
  TILE_GRID_CLS,
  TILE_NAME_CLS,
  TileBadge,
} from "./palette/PaletteParts";
import { sourceLabel } from "./palette/sourceLabels";
import { UserBlockSectionView } from "./palette/UserBlockSectionView";
import { PopupMenu, PopupMenuItem, RowActionButton } from "./ui/inspector";

// 組み込みカテゴリの表示順。ここに無い組み込みカテゴリは ``uncategorized`` の直前に
// 文字列の昇順で出す (ADR-0081 §8-B、無言で消さない)。backend `_BUILTIN_METADATA` に
// 新 category を追加するときは、ここにも追加して位置を決めること。CI ガード
// `tests/server/test_palette_category_order.py` が backend のカテゴリ集合 ⊆
// CATEGORY_ORDER であることを継続的に検証する。
const CATEGORY_ORDER = [
  "sources",
  "mathops",
  // SPEC-0012 / ADR-0059 (v5.5.0): 状態を持つ非線形要素 (Rate Limiter / Relay)。
  // 業界標準ツールと同じ「discontinuities」名。mathops の隣で「動的な非線形」を集約。
  "discontinuities",
  // SPEC-0008 / ADR-0059 (v5.1.0): 静的非線形マップ (math 近傍)
  "lookup",
  // SPEC-0009 / ADR-0059 (v5.2.0): 任意式評価 (math 近傍)
  "userfunc",
  "continuous",
  "discrete",
  "logic",
  "routing",
  "sinks",
  "subsystems",
  // ADR-0058: Subsystem 内部に置く境界ブロック (Inport / Outport / Trigger /
  // Enable) を集約した「control」カテゴリ。subsystems の直後に並べて palette
  // 上の位置を「Subsystem 関連の隣」にする。
  "control",
  "uncategorized",
] as const;

/** ユーザーブロックのセクションの折りたたみ状態キーの接頭辞 (組み込みカテゴリと衝突させない)。 */
const USER_SECTION_KEY_PREFIX = "user::";

/** 開いている操作メニューの位置 (画面座標)。 */
interface MenuPosition {
  x: number;
  y: number;
}

/**
 * ブロックが検索文字列に一致するか。
 *
 * 組み込み: 両言語の表示名 + 検索別名 + カテゴリ + tags (従来どおり)。ユーザーブロックは
 * さらに型名・説明・読み込み元のラベルも対象にする (ADR-0081 §8-B)。
 */
function matchesSearch(
  block: BlockMetadata,
  filter: string,
  sourceLabelOf: (id: string) => string,
): boolean {
  if (!filter) return true;
  // サーバの JSON の形が崩れていても (category が null・tags 欠落等) 例外にしない
  const hit = (s: unknown): boolean =>
    typeof s === "string" && s.toLowerCase().includes(filter);
  if (searchableDisplayNames(block).some(hit)) return true;
  if (hit(block.category)) return true;
  if (Array.isArray(block.tags) && block.tags.some(hit)) return true;
  if (!isUserBlock(block)) return false;
  return [
    block.type_path,
    localizedDocstringSummary(block),
    sourceLabelOf(block.source as string),
  ].some(hit);
}

/** ブロックパレット (左ペイン)。 */
export function BlockPalette(): JSX.Element {
  const { t, i18n } = useTranslation();
  const { data, isLoading, error } = useQuery({
    queryKey: BLOCKS_REGISTRY_QUERY_KEY,
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  // ADR-0029: Library registry も同様に長期 cache。drag-start 時には ref のみ
  // 運び、drop 経路で別 query が body を取りに行く。
  const { data: libraryData } = useQuery({
    queryKey: ["libraries-registry"],
    queryFn: listLibraries,
    staleTime: 60 * 60 * 1000,
  });
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [menu, setMenu] = useState<MenuPosition | null>(null);
  const { reload, pending: reloadPending } = useBlockReload();
  const closeMenu = useCallback(() => setMenu(null), []);
  const menuAnchorRef = useRef<HTMLSpanElement>(null);

  // ADR-0028: 言語切替時に block 表示名 / 検索結果が変わるため、``i18n.language`` を
  // useMemo の依存に含めて再計算する (registry 自体は 1 回 fetch + cache 維持)。
  const lang = i18n.language;
  const layout = useMemo(() => {
    if (!data) return null;
    const filter = search.trim().toLowerCase();
    const sourceById = new Map<string, BlockSourceInfo>(
      (data.sources ?? []).map((s) => [s.id, s]),
    );
    const labelOf = (id: string): string => sourceLabel(t, id, sourceById.get(id));
    return buildPaletteLayout(
      data,
      data.blocks.filter((b) => matchesSearch(b, filter, labelOf)),
      {
        categoryOrder: CATEGORY_ORDER,
        filtering: filter.length > 0,
        nameOf: (b) => localizedDisplayName(b),
      },
    );
    // ``lang`` 変化で sort 順 / 検索ヒットが変わるため依存に追加
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, lang, t]);

  // ADR-0029: Library entry の drag-start。``application/flode-library-entry-ref``
  // で参照のみを運ぶ (body は drop 経路で fetch、= ペイロード削減)。
  const handleLibraryDragStart = (
    event: React.DragEvent<HTMLDivElement>,
    library: LibraryMetadata,
    entry: LibraryEntryMetadata,
  ): void => {
    event.dataTransfer.setData(
      "application/flode-library-entry-ref",
      JSON.stringify({ library: library.name, entry: entry.id }),
    );
    event.dataTransfer.effectAllowed = "copy";
  };

  /** 検索フィルタを library entry に適用する (両言語名 + library 名)。 */
  const filterLibraryEntry = (
    library: LibraryMetadata,
    entry: LibraryEntryMetadata,
  ): boolean => {
    const filter = search.trim().toLowerCase();
    if (!filter) return true;
    const candidates = [
      entry.id,
      entry.display_name,
      entry.display_name_i18n?.en ?? "",
      entry.display_name_i18n?.ja ?? "",
      library.name,
      library.display_name,
    ];
    return candidates.some((c) => c.toLowerCase().includes(filter));
  };

  const toggle = (key: string): void =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));

  if (isLoading) {
    return <div className="p-3 text-xs text-slate-500">{t("palette.loading")}</div>;
  }
  if (error) {
    return (
      <div className="p-3 text-xs text-rose-600">
        {t("palette.error", { message: (error as Error).message })}
      </div>
    );
  }
  if (!data || !layout) return <div />;

  const isFiltering = search.trim().length > 0;
  const userBlocksStatus = data.user_blocks;
  const reloadAllowed = userBlocksStatus?.reload_allowed === true;
  const reloadReason = reloadAllowed
    ? undefined
    : cleanServerText(userBlocksStatus?.reload_reason, MAX_MESSAGE_CHARS) || undefined;
  // 読み込み元・読み込みエラー・無効の理由のどれかがあれば最下部の欄を出す
  // (ユーザーブロックが未設定なら出さない。⋯ メニューの「再読み込み」は残る)
  const showLoadPanel =
    userBlocksStatus !== undefined &&
    ((data.sources ?? []).length > 0 ||
      (data.load_errors ?? []).length > 0 ||
      !userBlocksStatus.enabled);
  const openMenuAt = (e: React.MouseEvent): void => {
    e.preventDefault();
    setMenu({ x: e.clientX, y: e.clientY });
  };
  const noMatch =
    layout.userSections.length === 0 &&
    layout.builtinGroups.length === 0 &&
    (libraryData?.libraries ?? []).every(
      (lib) => !lib.entries.some((e) => filterLibraryEntry(lib, e)),
    );

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="block-palette">
      <div className="flex shrink-0 items-center gap-1 border-b border-slate-200 p-2.5">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("palette.search")}
          className="min-w-0 flex-1 rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label={t("palette.search")}
        />
        {userBlocksStatus !== undefined && (
          <span ref={menuAnchorRef} className="flex shrink-0">
            <RowActionButton
              icon="more"
              ariaLabel={t("palette.menu.aria")}
              testId="palette-menu-button"
              onClick={() => {
                // トグル: 開いていれば閉じ、閉じていればボタンの左下に出す
                // (ボタン内の pointerdown では PopupMenu が閉じない = anchorRef)
                const rect = menuAnchorRef.current?.getBoundingClientRect();
                setMenu((prev) =>
                  prev !== null ? null : { x: rect?.left ?? 0, y: rect?.bottom ?? 0 },
                );
              }}
            />
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
        {noMatch && (
          <div className="p-3 text-xs text-slate-500">{t("palette.no_match")}</div>
        )}
        {/* ADR-0081 §8-B: ユーザーブロックのセクション (組み込みより上) */}
        {layout.userSections.map((section) => {
          const key = `${USER_SECTION_KEY_PREFIX}${section.id}`;
          return (
            <UserBlockSectionView
              key={key}
              section={section}
              collapsed={Boolean(collapsed[key]) && !isFiltering}
              onToggle={() => toggle(key)}
              onContextMenu={openMenuAt}
            />
          );
        })}
        {layout.builtinGroups.map(({ category, blocks }) => {
          const isCollapsed = Boolean(collapsed[category]) && !isFiltering;
          return (
            <div key={category} className="mb-1">
              <CategoryHeader
                label={
                  (CATEGORY_ORDER as readonly string[]).includes(category)
                    ? t(`palette.category.${category}` as "palette.category.sources")
                    : // CATEGORY_ORDER 外のカテゴリは訳語が無いのでカテゴリ名のまま出す
                      cleanServerText(category, MAX_LABEL_CHARS)
                }
                count={blocks.length}
                collapsed={isCollapsed}
                onToggle={() => toggle(category)}
              />
              {!isCollapsed && (
                <div className={TILE_GRID_CLS}>
                  {blocks.map((b) => (
                    <BlockTile key={b.type_path} block={b} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {/* ADR-0029: Libraries セクション。組み込み + ユーザー定義の `.flwlib.json` を
            一覧表示する。各 entry は drag で `application/flode-library-entry-ref` を運ぶ。 */}
        {(libraryData?.libraries ?? []).map((library) => {
          const libCatKey = `lib::${library.name}`;
          const isCollapsed = Boolean(collapsed[libCatKey]) && !isFiltering;
          const visibleEntries = library.entries.filter((e) =>
            filterLibraryEntry(library, e),
          );
          if (visibleEntries.length === 0) return null;
          const libDispName = localizeName(library, library.name);
          return (
            <div key={libCatKey} className="mb-1">
              {/* v0.33.1: Library セクションも slate 系 (built-in と同じ)。区別は
                  「Library · 名前」プレフィクスと「LIB」バッジで視認する。 */}
              <CategoryHeader
                label={`${t("palette.library_prefix", { defaultValue: "Library" })} · ${libDispName}`}
                count={visibleEntries.length}
                collapsed={isCollapsed}
                onToggle={() => toggle(libCatKey)}
              />
              {!isCollapsed && (
                <div className={TILE_GRID_CLS}>
                  {visibleEntries.map((entry) => {
                    const dispName = localizeName(entry, entry.id);
                    return (
                      <div
                        key={`${library.name}::${entry.id}`}
                        draggable
                        onDragStart={(e) =>
                          handleLibraryDragStart(e, library, entry)
                        }
                        className={TILE_CLS}
                        title={dispName}
                      >
                        <div className={TILE_GLYPH_CLS}>
                          <BlockGlyph typePath="flode.subsystems.subsystem.Subsystem" />
                        </div>
                        <div className={TILE_NAME_CLS}>{dispName}</div>
                        <TileBadge text="LIB" />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {showLoadPanel && (
        <LoadErrorsPanel
          registry={data}
          onReload={() => void reload()}
          reloadPending={reloadPending}
        />
      )}
      {menu !== null && (
        <PopupMenu
          x={menu.x}
          y={menu.y}
          onClose={closeMenu}
          anchorRef={menuAnchorRef}
          ariaLabel={t("palette.menu.aria")}
          testId="palette-menu"
        >
          <PopupMenuItem
            label={
              reloadPending ? t("palette.reload.pending") : t("palette.menu.reload")
            }
            disabled={!reloadAllowed || reloadPending}
            title={reloadReason}
            testId="palette-menu-reload"
            onClick={() => {
              setMenu(null);
              void reload();
            }}
          />
        </PopupMenu>
      )}
    </div>
  );
}
