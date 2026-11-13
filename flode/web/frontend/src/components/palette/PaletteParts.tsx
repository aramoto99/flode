// ブロックパレットの部品 (タイル・バッジ・折りたたみ見出し)。組み込みカテゴリ・
// ユーザーブロックのセクション・Library セクションで共用する (ADR-0019 §(3) / ADR-0029 /
// ADR-0081 §8-B)。

import { BlockGlyph } from "../../lib/blockGlyphs";
import { localizedDisplayName, localizedDocstringSummary } from "../../lib/blockI18n";
import { buildDefaultParams } from "../../lib/idGenerator";
import { cleanServerText, MAX_PATH_CHARS } from "../../lib/untrustedText";
import type { BlockMetadata } from "../../types/api";

/** タイルのクラス (v0.33.2: 角丸を撤廃して角ばった見た目)。 */
export const TILE_CLS =
  "group flex cursor-grab flex-col items-center gap-0.5 border border-transparent px-1 py-1.5 text-center hover:border-blue-300 hover:bg-blue-50/50 active:cursor-grabbing";
/** タイル内 glyph 枠のクラス (v0.33.0: glyph は slate-600 を継承する中性色)。 */
export const TILE_GLYPH_CLS =
  "flex h-9 w-9 items-center justify-center border border-slate-200 bg-white p-1 text-slate-600 transition-colors group-hover:border-blue-400";
/** タイル内の表示名のクラス。 */
export const TILE_NAME_CLS = "w-full truncate text-[10px] font-medium text-slate-700";
/** タイルを並べる 2 列 grid のクラス。 */
export const TILE_GRID_CLS = "grid grid-cols-2 gap-1 px-1 pt-1";

/**
 * タイル下の小さな印 (Library の ``LIB``、ユーザーブロックの ``PY``)。組み込みと
 * 見分けるための控えめな表示で、``title`` に出所を出す。
 */
export function TileBadge({
  text,
  title,
}: {
  text: string;
  title?: string;
}): JSX.Element {
  return (
    <span
      title={title}
      className="rounded bg-slate-100 px-1 text-[8px] uppercase tracking-wide text-slate-500"
    >
      {text}
    </span>
  );
}

/**
 * カテゴリ / セクションの折りたたみ見出し (▾ ラベル 件数)。
 *
 * ``onContextMenu`` を渡すと右クリックで操作メニューを開ける (ユーザーブロックの
 * セクション、ADR-0081 §8-B)。``title`` はツールチップ (読み込み元のルートとファイル一覧)。
 */
export function CategoryHeader({
  label,
  count,
  collapsed,
  onToggle,
  onContextMenu,
  title,
  testId,
}: {
  label: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  title?: string;
  testId?: string;
}): JSX.Element {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-1 rounded-md px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500 hover:bg-slate-100"
      onClick={onToggle}
      onContextMenu={onContextMenu}
      aria-expanded={!collapsed}
      title={title}
      data-testid={testId}
    >
      <span className="w-3 text-slate-400">{collapsed ? "▸" : "▾"}</span>
      <span className="min-w-0 truncate">{label}</span>
      <span className="ml-auto rounded bg-slate-100 px-1.5 py-px text-[9px] text-slate-500">
        {count}
      </span>
    </button>
  );
}

/**
 * registry のブロック 1 つのタイル (drag-start で型名と既定パラメータを積む)。
 *
 * ``badge`` を渡すとユーザーブロックの印を出し、ツールチップに型名と読み込み元を足す。
 * 組み込みブロック (``badge`` なし) の見た目は従来どおり。
 */
export function BlockTile({
  block,
  badge,
}: {
  block: BlockMetadata;
  badge?: { text: string; title: string };
}): JSX.Element {
  // ADR-0028: 現在言語で表示名・docstring を取り出す (ユーザーブロックは整形済み)
  const dispName = localizedDisplayName(block);
  const summary = localizedDocstringSummary(block);
  const baseTitle = summary ? `${dispName} — ${summary}` : dispName;
  const title =
    badge === undefined
      ? baseTitle
      : [baseTitle, cleanServerText(block.type_path, MAX_PATH_CHARS), badge.title].join("\n");
  const handleDragStart = (event: React.DragEvent<HTMLDivElement>): void => {
    event.dataTransfer.setData("application/flode-block-type", block.type_path);
    event.dataTransfer.setData(
      "application/flode-default-params",
      JSON.stringify(
        buildDefaultParams(block.params_spec, { isContainer: block.is_container }),
      ),
    );
    event.dataTransfer.effectAllowed = "copy";
  };
  return (
    <div
      draggable
      onDragStart={handleDragStart}
      className={TILE_CLS}
      title={title}
      data-testid="palette-block-tile"
      data-type-path={block.type_path}
    >
      <div className={TILE_GLYPH_CLS}>
        <BlockGlyph typePath={block.type_path} />
      </div>
      <div className={TILE_NAME_CLS}>{dispName}</div>
      {badge !== undefined && <TileBadge text={badge.text} title={badge.title} />}
    </div>
  );
}
