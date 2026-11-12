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
// SPEC-0032 §1.3 / ADR-0080: ユーザーライブラリ (マイブロック) は独立セクションとして
// **最上部** (組み込みカテゴリより上) に置き、``category_suffix`` をサブ見出しにする。
// エントリの右クリックで編集 / 削除、セクション見出しのメニューで書き出し / 再読み込み、
// 検索欄の横のメニューで取り込み / 再読み込みを行う。

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  deleteImportedLibrary,
  deleteLibraryEntry,
  exportLibrary,
  importLibrary,
  listBlockMetadata,
  reloadLibraries,
} from "../api/client";
import { BlockGlyph } from "../lib/blockGlyphs";
import {
  localizeName,
  localizedDisplayName,
  localizedDocstringSummary,
  searchableDisplayNames,
} from "../lib/blockI18n";
import { PYTHON_FUNCTION_TYPE, SUBSYSTEM_TYPE } from "../lib/blockTypes";
import { dialog } from "../lib/dialogService";
import { downloadBlob } from "../lib/downloadFile";
import { buildDefaultParams } from "../lib/idGenerator";
import {
  describeLibraryError,
  describeWriteDisabledReason,
  entryWriteDisabledReason,
  libraryImportDisabledReason,
  libraryReloadDisabledReason,
} from "../lib/libraryErrors";
import { LIBRARIES_QUERY_KEY, useLibrariesQuery } from "../lib/librariesQuery";
import { pushToast } from "../store/toastStore";
import type {
  BlockMetadata,
  LibraryEntryMetadata,
  LibraryImportReport,
  LibraryMetadata,
} from "../types/api";
import { ImportLibraryDialog, LibraryEntryDialog } from "./LibraryDialogs";
import {
  MenuButton,
  PopupMenu,
  PopupMenuItem,
  SectionDivider,
} from "./ui/inspector";

// 重要: このリストは palette 表示の whitelist として働く (= 含まれない category
// のブロックは silently filter で除外される)。backend `_BUILTIN_METADATA` に新
// category を追加するときは、ここにも追加すること。CI ガード
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

/** ライブラリの出所: ユーザーライブラリ (マイブロック) / 取り込みライブラリ。 */
const ORIGIN_USER = "user";
const ORIGIN_IMPORTED = "imported";
/** マイブロックセクションの折りたたみ状態のキー。 */
const MY_BLOCKS_SECTION_KEY = "lib::my-blocks";
/** バッジ共通の class (既存の LIB バッジと同じ寸法)。 */
const BADGE_CLS = "rounded px-1 text-[8px] uppercase tracking-wide";

/** 開いている popup menu の種類と位置。 */
type PaletteMenu =
  | { kind: "palette"; x: number; y: number }
  | { kind: "library"; x: number; y: number; library: LibraryMetadata | null }
  | { kind: "entry"; x: number; y: number; entry: LibraryEntryMetadata };

/** 取り込み確認ダイアログに渡す dry-run の結果。 */
interface PendingImport {
  filename: string;
  content: string;
  report: LibraryImportReport;
}

const BYTES_PER_MIB = 1024 * 1024;
/**
 * 取り込めるライブラリファイルの最大サイズ。backend の本文上限は 16 MiB だが、
 * ファイル本文は JSON 文字列として送る (引用符・改行・非 ASCII のエスケープで膨らむ)
 * ので、その分の余裕を見て 12 MiB にする。超えるファイルは読み込まずに拒否する。
 */
const MAX_IMPORT_FILE_BYTES = 12 * BYTES_PER_MIB;

/**
 * セクション見出し (折りたたみトグル + 件数 + 任意のメニューボタン)。
 * ``onMenu`` を渡すと、見出しの右クリックと ⋯ ボタンの両方から同じメニューを開ける。
 */
function SectionHeader({
  label,
  count,
  collapsed,
  onToggle,
  onMenu,
  menuLabel,
  menuOpen = false,
  testId,
}: {
  label: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  onMenu?: (pos: { x: number; y: number }) => void;
  menuLabel?: string;
  /** この見出しのメニューが開いているか (⋯ ボタンのトグル用)。 */
  menuOpen?: boolean;
  testId?: string;
}): JSX.Element {
  return (
    <div
      className="flex items-center hover:bg-slate-100"
      onContextMenu={
        onMenu
          ? (e) => {
              e.preventDefault();
              onMenu({ x: e.clientX, y: e.clientY });
            }
          : undefined
      }
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-1 px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500"
        onClick={onToggle}
        aria-expanded={!collapsed}
        data-testid={testId}
      >
        <span className="w-3 shrink-0 text-slate-400">{collapsed ? "▸" : "▾"}</span>
        <span className="min-w-0 truncate">{label}</span>
        <span className="ml-auto shrink-0 rounded bg-slate-100 px-1.5 py-px text-[9px] text-slate-500">
          {count}
        </span>
      </button>
      {onMenu && menuLabel !== undefined && (
        <MenuButton
          ariaLabel={menuLabel}
          onOpen={onMenu}
          open={menuOpen}
          testId={testId ? `${testId}-menu` : undefined}
        />
      )}
    </div>
  );
}

/**
 * ライブラリエントリ 1 件のタイル (drag で配置)。``PY`` バッジは Python コードを含む
 * エントリ (入れ子を含む) に全ライブラリで付ける。マイブロックは種別バッジ (``SUB``)、
 * それ以外のライブラリは従来どおり ``LIB`` バッジ。
 */
function LibraryEntryTile({
  library,
  entry,
  onContextMenu,
}: {
  library: LibraryMetadata;
  entry: LibraryEntryMetadata;
  onContextMenu?: (e: React.MouseEvent) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const dispName = localizeName(entry, entry.id);
  const isPython = entry.kind === "python_function";
  return (
    <div
      draggable
      onDragStart={(e) => {
        // ADR-0029: 参照のみを運ぶ (body は drop 経路で fetch、= ペイロード削減)
        e.dataTransfer.setData(
          "application/flode-library-entry-ref",
          JSON.stringify({ library: library.name, entry: entry.id }),
        );
        e.dataTransfer.effectAllowed = "copy";
      }}
      onContextMenu={onContextMenu}
      // v0.33.2: 角丸撤廃 (built-in と同じ)
      className="group flex cursor-grab flex-col items-center gap-0.5 border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
      title={entry.description ? `${dispName} — ${entry.description}` : dispName}
      data-testid={`palette-entry-${library.name}-${entry.id}`}
    >
      <div className="flex h-9 w-9 items-center justify-center border border-slate-200 bg-white p-1 text-slate-600 transition-colors group-hover:border-blue-400">
        <BlockGlyph typePath={isPython ? PYTHON_FUNCTION_TYPE : SUBSYSTEM_TYPE} />
      </div>
      <div className="w-full truncate text-[10px] font-medium text-slate-700">
        {dispName}
      </div>
      <div className="flex items-center gap-0.5">
        {library.origin !== ORIGIN_USER ? (
          <span className={`${BADGE_CLS} bg-slate-100 text-slate-500`}>
            {t("palette.badge.lib")}
          </span>
        ) : (
          !isPython && (
            <span className={`${BADGE_CLS} bg-slate-100 text-slate-500`}>
              {t("palette.badge.subsystem")}
            </span>
          )
        )}
        {entry.contains_python && (
          <span
            className={`${BADGE_CLS} bg-amber-100 text-amber-800`}
            title={t("palette.badge.python_title")}
            data-testid={`palette-entry-py-${library.name}-${entry.id}`}
          >
            {t("palette.badge.python")}
          </span>
        )}
      </div>
    </div>
  );
}

/** ブロックパレット (左ペイン)。組み込みブロックとライブラリエントリを一覧・検索・drag する。 */
export function BlockPalette(): JSX.Element {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["blocks-registry"],
    queryFn: listBlockMetadata,
    staleTime: 60 * 60 * 1000,
  });
  // ADR-0080 §A5: ライブラリ一覧は実行時に変わるので常に stale 扱い + focus で取り直す。
  // drag-start 時には ref のみ運び、drop 経路で別 fetch が body を取りに行く。
  const { data: libraryData } = useLibrariesQuery();
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [showLoadErrors, setShowLoadErrors] = useState(false);
  const [menu, setMenu] = useState<PaletteMenu | null>(null);
  const [editingEntry, setEditingEntry] = useState<LibraryEntryMetadata | null>(null);
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const closeMenu = useCallback(() => setMenu(null), []);

  // ADR-0028: 言語切替時に block 表示名 / 検索結果が変わるため、``i18n.language`` を
  // useMemo の依存に含めて再計算する (registry 自体は 1 回 fetch + cache 維持)。
  const lang = i18n.language;
  const blocksByCategory = useMemo(() => {
    if (!data) return {} as Record<string, BlockMetadata[]>;
    const filter = search.trim().toLowerCase();
    const filtered = data.blocks.filter((b) => {
      if (!filter) return true;
      // 両言語 display_name + category + tags を検索対象に (ADR-0028 §(4))
      const names = searchableDisplayNames(b).map((s) => s.toLowerCase());
      if (names.some((n) => n.includes(filter))) return true;
      return (
        b.category.toLowerCase().includes(filter) ||
        b.tags.some((tag) => tag.toLowerCase().includes(filter))
      );
    });
    const grouped: Record<string, BlockMetadata[]> = {};
    for (const b of filtered) {
      const key = b.category;
      if (!grouped[key]) grouped[key] = [];
      grouped[key]!.push(b);
    }
    for (const list of Object.values(grouped)) {
      list.sort((a, b) =>
        localizedDisplayName(a).localeCompare(localizedDisplayName(b)),
      );
    }
    return grouped;
    // ``lang`` 変化で sort 順 / 検索ヒットが変わるため依存に追加
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, search, lang]);

  const handleDragStart = (
    event: React.DragEvent<HTMLDivElement>,
    block: BlockMetadata,
  ): void => {
    event.dataTransfer.setData("application/flode-block-type", block.type_path);
    event.dataTransfer.setData(
      "application/flode-default-params",
      JSON.stringify(
        buildDefaultParams(block.params_spec, { isContainer: block.is_container }),
      ),
    );
    event.dataTransfer.effectAllowed = "copy";
  };

  /** 検索フィルタを library entry に適用する (両言語名 + 分類 + library 名)。 */
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
      entry.category_suffix,
      library.name,
      library.display_name,
    ];
    return candidates.some((c) => c.toLowerCase().includes(filter));
  };

  const invalidateLibraries = (): void => {
    void queryClient.invalidateQueries({ queryKey: LIBRARIES_QUERY_KEY });
  };

  /** ライブラリ API の失敗を通知し、一覧を取り直す (別タブでの変更に追従する)。 */
  const reportLibraryError = (err: unknown): void => {
    pushToast({ severity: "error", message: describeLibraryError(t, err) });
    invalidateLibraries();
  };

  const handleReload = async (): Promise<void> => {
    try {
      const fresh = await reloadLibraries();
      queryClient.setQueryData(LIBRARIES_QUERY_KEY, fresh);
      pushToast({ severity: "success", message: t("palette.toast.reloaded") });
    } catch (err) {
      reportLibraryError(err);
    }
  };

  const handleExport = async (library: LibraryMetadata): Promise<void> => {
    try {
      const { filename, text } = await exportLibrary(library.name);
      downloadBlob(new Blob([text], { type: "application/json" }), filename);
    } catch (err) {
      reportLibraryError(err);
    }
  };

  const handleDeleteLibrary = async (library: LibraryMetadata): Promise<void> => {
    const name = localizeName(library, library.name);
    const ok = await dialog.confirm(t("palette.confirm.delete_library", { name }), {
      title: t("palette.menu.delete_library"),
      okLabel: t("modal.button.delete"),
      variant: "danger",
    });
    if (!ok) return;
    try {
      await deleteImportedLibrary(library.name);
      invalidateLibraries();
      pushToast({
        severity: "success",
        message: t("palette.toast.library_deleted", { name }),
      });
    } catch (err) {
      reportLibraryError(err);
    }
  };

  const handleDeleteEntry = async (entry: LibraryEntryMetadata): Promise<void> => {
    const ok = await dialog.confirm(
      t("palette.confirm.delete_entry", { name: entry.display_name }),
      {
        title: t("palette.menu.delete_entry"),
        okLabel: t("modal.button.delete"),
        variant: "danger",
      },
    );
    if (!ok) return;
    try {
      await deleteLibraryEntry(entry.id, entry.revision);
      invalidateLibraries();
      pushToast({
        severity: "success",
        message: t("palette.toast.entry_deleted", { name: entry.display_name }),
      });
    } catch (err) {
      reportLibraryError(err);
    }
  };

  /** 選択されたファイルを文字列で読み、dry-run の結果を確認ダイアログに渡す。 */
  const handleImportFile = async (file: File): Promise<void> => {
    if (file.size > MAX_IMPORT_FILE_BYTES) {
      // 巨大なファイルはメモリに読まない (サーバも本文サイズで拒否する)
      pushToast({
        severity: "error",
        message: t("palette.toast.import_too_large", {
          max_mb: MAX_IMPORT_FILE_BYTES / BYTES_PER_MIB,
        }),
      });
      return;
    }
    try {
      const content = await file.text();
      const report = await importLibrary(content, { dryRun: true, filename: file.name });
      setPendingImport({ filename: file.name, content, report });
    } catch (err) {
      reportLibraryError(err);
    }
  };

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
  if (!data) return <div />;

  const visibleCategories = CATEGORY_ORDER.filter(
    (c) => (blocksByCategory[c]?.length ?? 0) > 0,
  );
  const isFiltering = search.trim().length > 0;

  const libraries = libraryData?.libraries ?? [];
  const loadErrors = libraryData?.load_errors ?? [];
  const userStatus = libraryData?.user_library;
  const userLibrary = libraries.find((lib) => lib.origin === ORIGIN_USER);
  const otherLibraries = libraries.filter((lib) => lib.origin !== ORIGIN_USER);

  const entryDisabledTitle = describeWriteDisabledReason(
    t,
    entryWriteDisabledReason(userStatus),
  );
  const importDisabledTitle = describeWriteDisabledReason(
    t,
    libraryImportDisabledReason(userStatus),
  );
  const reloadDisabledTitle = describeWriteDisabledReason(
    t,
    libraryReloadDisabledReason(userStatus),
  );

  // マイブロック: 分類なし → 分類 (名前順) の順に、各グループ内は表示名順
  const myEntries = (userLibrary?.entries ?? []).filter((e) =>
    userLibrary ? filterLibraryEntry(userLibrary, e) : false,
  );
  const myGroups = new Map<string, LibraryEntryMetadata[]>();
  for (const entry of myEntries) {
    const group = myGroups.get(entry.category_suffix) ?? [];
    group.push(entry);
    myGroups.set(entry.category_suffix, group);
  }
  const myGroupKeys = [...myGroups.keys()].sort((a, b) => a.localeCompare(b));
  for (const group of myGroups.values()) {
    group.sort((a, b) => a.display_name.localeCompare(b.display_name));
  }
  // 一覧が取れている間は常にセクションを出す (空・無効のときは 1 行で理由を示す)。
  // 検索中は一致するエントリがあるときだけ出す。
  const showMyBlocks =
    userStatus !== undefined && (isFiltering ? myEntries.length > 0 : true);
  const myBlocksCollapsed = collapsed[MY_BLOCKS_SECTION_KEY] && !isFiltering;

  const nothingMatches =
    isFiltering &&
    visibleCategories.length === 0 &&
    myEntries.length === 0 &&
    otherLibraries.every(
      (lib) => !lib.entries.some((e) => filterLibraryEntry(lib, e)),
    );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b border-slate-200 p-2.5">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("palette.search")}
          className="min-w-0 flex-1 rounded-md border border-slate-300 bg-slate-50 px-2.5 py-1.5 text-xs placeholder:text-slate-400 focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label={t("palette.search")}
        />
        <MenuButton
          ariaLabel={t("palette.menu.libraries")}
          onOpen={(pos) => setMenu({ kind: "palette", ...pos })}
          open={menu?.kind === "palette"}
          testId="palette-menu-button"
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          data-testid="palette-import-file"
          onChange={(e) => {
            const file = e.target.files?.[0];
            // 同じファイルを続けて選び直せるように値を戻す
            e.target.value = "";
            if (file) void handleImportFile(file);
          }}
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
        {/* SPEC-0032 §1.3-1: マイブロックは最上部 (組み込みカテゴリより上)。 */}
        {showMyBlocks && (
          <div className="mb-1" data-testid="palette-section-my-blocks">
            <SectionHeader
              label={t("palette.my_blocks")}
              count={myEntries.length}
              collapsed={Boolean(myBlocksCollapsed)}
              onToggle={() =>
                setCollapsed((prev) => ({
                  ...prev,
                  [MY_BLOCKS_SECTION_KEY]: !prev[MY_BLOCKS_SECTION_KEY],
                }))
              }
              onMenu={(pos) =>
                setMenu({ kind: "library", ...pos, library: userLibrary ?? null })
              }
              menuLabel={t("palette.menu.section", { name: t("palette.my_blocks") })}
              menuOpen={
                menu?.kind === "library" &&
                (menu.library === null || menu.library.origin === ORIGIN_USER)
              }
              testId="palette-my-blocks-header"
            />
            {!myBlocksCollapsed &&
              (myEntries.length === 0 || userLibrary === undefined ? (
                <p
                  className="px-2 py-1 text-[10px] leading-snug text-slate-500"
                  data-testid="palette-my-blocks-empty"
                >
                  {entryDisabledTitle ?? t("palette.my_blocks_hint")}
                </p>
              ) : (
                myGroupKeys.map((groupKey) => (
                  <div key={groupKey} data-testid={`palette-my-blocks-group-${groupKey}`}>
                    {groupKey !== "" && (
                      <div className="px-2">
                        <SectionDivider label={groupKey} />
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-1 px-1 pt-1">
                      {(myGroups.get(groupKey) ?? []).map((entry) => (
                        <LibraryEntryTile
                          key={entry.id}
                          library={userLibrary}
                          entry={entry}
                          onContextMenu={(e) => {
                            e.preventDefault();
                            setMenu({ kind: "entry", x: e.clientX, y: e.clientY, entry });
                          }}
                        />
                      ))}
                    </div>
                  </div>
                ))
              ))}
          </div>
        )}
        {nothingMatches ? (
          <div className="p-3 text-xs text-slate-500">{t("palette.no_match")}</div>
        ) : (
          visibleCategories.map((cat) => {
            const isCollapsed = collapsed[cat] && !isFiltering;
            const blocks = blocksByCategory[cat] ?? [];
            return (
              <div key={cat} className="mb-1">
                <SectionHeader
                  label={t(`palette.category.${cat}` as const)}
                  count={blocks.length}
                  collapsed={Boolean(isCollapsed)}
                  onToggle={() =>
                    setCollapsed((prev) => ({ ...prev, [cat]: !prev[cat] }))
                  }
                />
                {!isCollapsed && (
                  <div className="grid grid-cols-2 gap-1 px-1 pt-1">
                    {blocks.map((b) => {
                      // ADR-0028: 現在言語で表示名・docstring を取り出す。
                      // ``i18n.language`` 変化で本コンポーネントが再 render され、
                      // useMemo 経由で再計算されるため、ここはストレートに helper を呼ぶ。
                      const dispName = localizedDisplayName(b);
                      const summary = localizedDocstringSummary(b);
                      return (
                        <div
                          key={b.type_path}
                          draggable
                          onDragStart={(e) => handleDragStart(e, b)}
                          // v0.33.2: 角丸を撤廃して角ばった見た目に (ユーザー要望)
                          className="group flex cursor-grab flex-col items-center gap-0.5 border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing"
                          title={summary ? `${dispName} — ${summary}` : dispName}
                        >
                          <div
                            // v0.33.0: per-block color 撤廃。glyph は CSS で
                            // slate-600 を継承 (= 全カテゴリ統一の中性色)。
                            className="flex h-9 w-9 items-center justify-center border border-slate-200 bg-white p-1 text-slate-600 transition-colors group-hover:border-blue-400"
                          >
                            <BlockGlyph typePath={b.type_path} />
                          </div>
                          <div className="w-full truncate text-[10px] font-medium text-slate-700">
                            {dispName}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })
        )}
        {/* ADR-0029: その他のライブラリ (組み込み std / 取り込み / library_paths) は
            従来どおり「Library · 名前」セクションで組み込みカテゴリの後ろ。区別は
            プレフィクスと LIB バッジで視認する (v0.33.1: per-block color 撤廃)。 */}
        {otherLibraries.map((library) => {
          const libCatKey = `lib::${library.name}`;
          const isCollapsed = collapsed[libCatKey] && !isFiltering;
          const visibleEntries = library.entries.filter((e) =>
            filterLibraryEntry(library, e),
          );
          if (visibleEntries.length === 0) return null;
          const libDispName = localizeName(library, library.name);
          return (
            <div key={libCatKey} className="mb-1">
              <SectionHeader
                label={`${t("palette.library_prefix", { defaultValue: "Library" })} · ${libDispName}`}
                count={visibleEntries.length}
                collapsed={Boolean(isCollapsed)}
                onToggle={() =>
                  setCollapsed((prev) => ({
                    ...prev,
                    [libCatKey]: !prev[libCatKey],
                  }))
                }
                onMenu={
                  library.origin === ORIGIN_IMPORTED
                    ? (pos) => setMenu({ kind: "library", ...pos, library })
                    : undefined
                }
                menuLabel={t("palette.menu.section", { name: libDispName })}
                menuOpen={menu?.kind === "library" && menu.library?.name === library.name}
                testId={`palette-library-header-${library.name}`}
              />
              {!isCollapsed && (
                <div className="grid grid-cols-2 gap-1 px-1 pt-1">
                  {visibleEntries.map((entry) => (
                    <LibraryEntryTile key={entry.id} library={library} entry={entry} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {/* SPEC-0032 §1.8: 読み込めなかったライブラリファイル (パス + 理由)。 */}
        {loadErrors.length > 0 && !isFiltering && (
          <div className="mb-1" data-testid="palette-load-errors">
            <SectionHeader
              label={t("palette.load_errors")}
              count={loadErrors.length}
              collapsed={!showLoadErrors}
              onToggle={() => setShowLoadErrors((prev) => !prev)}
              testId="palette-load-errors-header"
            />
            {showLoadErrors && (
              <ul className="px-2 py-1">
                {loadErrors.map((e) => (
                  <li key={e.path} className="mb-1 text-[10px] leading-snug">
                    <div className="truncate font-mono text-slate-600" title={e.path}>
                      {e.path}
                    </div>
                    <div className="line-clamp-3 break-words text-rose-700" title={e.message}>
                      {e.message}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {menu?.kind === "palette" && (
        <PopupMenu x={menu.x} y={menu.y} onClose={closeMenu} testId="palette-menu">
          <PopupMenuItem
            label={t("palette.menu.import")}
            disabled={importDisabledTitle !== undefined}
            title={importDisabledTitle}
            testId="palette-menu-import"
            onClick={() => {
              closeMenu();
              fileInputRef.current?.click();
            }}
          />
          <PopupMenuItem
            label={t("palette.menu.reload")}
            disabled={reloadDisabledTitle !== undefined}
            title={reloadDisabledTitle}
            testId="palette-menu-reload"
            onClick={() => {
              closeMenu();
              void handleReload();
            }}
          />
        </PopupMenu>
      )}
      {menu?.kind === "library" && (
        <PopupMenu x={menu.x} y={menu.y} onClose={closeMenu} testId="palette-library-menu">
          <PopupMenuItem
            label={t("palette.menu.export")}
            // マイブロックはファイルが作られるまで書き出すものが無い
            disabled={menu.library === null}
            title={menu.library === null ? t("palette.menu.export_empty") : undefined}
            testId="palette-menu-export"
            onClick={() => {
              const { library } = menu;
              closeMenu();
              if (library) void handleExport(library);
            }}
          />
          {menu.library?.origin === ORIGIN_IMPORTED ? (
            <PopupMenuItem
              label={t("palette.menu.delete_library")}
              destructive
              disabled={importDisabledTitle !== undefined}
              title={importDisabledTitle}
              testId="palette-menu-delete-library"
              onClick={() => {
                const { library } = menu;
                closeMenu();
                if (library) void handleDeleteLibrary(library);
              }}
            />
          ) : (
            <PopupMenuItem
              label={t("palette.menu.reload")}
              disabled={reloadDisabledTitle !== undefined}
              title={reloadDisabledTitle}
              testId="palette-menu-section-reload"
              onClick={() => {
                closeMenu();
                void handleReload();
              }}
            />
          )}
        </PopupMenu>
      )}
      {menu?.kind === "entry" && (
        <PopupMenu x={menu.x} y={menu.y} onClose={closeMenu} testId="palette-entry-menu">
          <PopupMenuItem
            label={t("palette.menu.edit_entry")}
            disabled={entryDisabledTitle !== undefined}
            title={entryDisabledTitle}
            testId="palette-menu-edit-entry"
            onClick={() => {
              setEditingEntry(menu.entry);
              closeMenu();
            }}
          />
          <PopupMenuItem
            label={t("palette.menu.delete_entry")}
            destructive
            disabled={entryDisabledTitle !== undefined}
            title={entryDisabledTitle}
            testId="palette-menu-delete-entry"
            onClick={() => {
              const { entry } = menu;
              closeMenu();
              void handleDeleteEntry(entry);
            }}
          />
        </PopupMenu>
      )}
      {editingEntry !== null && (
        <LibraryEntryDialog
          target={{ kind: "edit", entry: editingEntry }}
          categories={myGroupKeys.filter((k) => k !== "")}
          onDone={() => setEditingEntry(null)}
          onClose={() => setEditingEntry(null)}
        />
      )}
      {pendingImport !== null && (
        <ImportLibraryDialog
          filename={pendingImport.filename}
          content={pendingImport.content}
          report={pendingImport.report}
          onImported={(result) => {
            setPendingImport(null);
            pushToast({
              severity: "success",
              message: t("palette.toast.imported", {
                name: result.library.display_name || result.library.name,
              }),
            });
          }}
          onClose={() => setPendingImport(null)}
        />
      )}
    </div>
  );
}
