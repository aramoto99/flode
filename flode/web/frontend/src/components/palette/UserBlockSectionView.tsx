// ADR-0081 §8-B: パレットのユーザーブロックのセクション (読み込み元 1 件分)。
//
// 見出し = 読み込み元のラベルとブロック数 (ツールチップにルートと読んだファイル一覧、
// 右クリックで操作メニュー)。中身 = カテゴリ未宣言のブロックを直下に、宣言カテゴリを
// サブ見出し (翻訳しない) で。ブロックが 0 件なら 1 行の説明。

import { useTranslation } from "react-i18next";

import type { UserBlockSection } from "../../lib/userBlocks";
import { SectionDivider } from "../ui/inspector";
import { BlockTile, CategoryHeader, TILE_GRID_CLS } from "./PaletteParts";
import { sourceLabel, sourceTooltip } from "./sourceLabels";

/**
 * ユーザーブロックのセクション 1 件。
 *
 * @param section - ``buildPaletteLayout`` が作ったセクション。
 * @param collapsed - 折りたたみ中か。
 * @param onToggle - 見出しクリック。
 * @param onContextMenu - 見出しの右クリック (操作メニューを開く)。
 */
export function UserBlockSectionView({
  section,
  collapsed,
  onToggle,
  onContextMenu,
}: {
  section: UserBlockSection;
  collapsed: boolean;
  onToggle: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
}): JSX.Element {
  const { t } = useTranslation();
  const label = sourceLabel(t, section.id, section.source);
  const badge = {
    text: t("palette.user.badge"),
    title: t("palette.user.from", { source: label }),
  };
  return (
    <div className="mb-1" data-testid="palette-user-section" data-source-id={section.id}>
      <CategoryHeader
        label={label}
        count={section.count}
        collapsed={collapsed}
        onToggle={onToggle}
        onContextMenu={onContextMenu}
        title={sourceTooltip(t, label, section.source)}
        testId="palette-user-section-header"
      />
      {!collapsed && section.count === 0 && (
        <div className="px-3 py-1 text-[10px] text-slate-500" data-testid="palette-user-section-empty">
          {t("palette.user.empty")}
        </div>
      )}
      {!collapsed && section.direct.length > 0 && (
        <div className={TILE_GRID_CLS}>
          {section.direct.map((b) => (
            <BlockTile key={b.type_path} block={b} badge={badge} />
          ))}
        </div>
      )}
      {!collapsed &&
        section.groups.map((group) => (
          <div key={group.category} data-testid="palette-user-subgroup">
            <div className="px-2">
              {/* カテゴリは翻訳もしないし大小文字も変えない (Filters と filters を見分ける) */}
              <SectionDivider label={group.category} uppercase={false} />
            </div>
            <div className={TILE_GRID_CLS}>
              {group.blocks.map((b) => (
                <BlockTile key={b.type_path} block={b} badge={badge} />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}
