// ADR-0081 §8-B / §6-D: パレットに出す読み込み元の見出しラベルとツールチップ。
//
// 見出しラベル: ワークスペース = i18n 文言、dirs = 名前、modules = モジュール名。
// ツールチップ: ルート (表示用パス) と読んだファイルの一覧 (ADR-0081 §6: 読んだファイルを
// 必ず画面に出す)。サーバ由来の文字列はすべて ``cleanServerText`` で整形する。

import type { TFunction } from "i18next";

import {
  cleanServerText,
  MAX_LABEL_CHARS,
  MAX_PATH_CHARS,
} from "../../lib/untrustedText";
import type { BlockSourceInfo } from "../../types/api";

const WORKSPACE_SOURCE_ID = "workspace";
const SOURCE_ID_PREFIX = /^(dir|module):/;
/** ツールチップに並べるファイル数の上限 (超えた分は件数だけ出す)。 */
export const MAX_TOOLTIP_FILES = 30;

/**
 * 読み込み元の見出しラベル。
 *
 * @param t - i18next の ``t``。
 * @param id - 読み込み元 id (``BlockMetadata.source`` / ``load_errors[].source``)。
 * @param source - ``sources[]`` の情報 (無ければ ``null`` / ``undefined``、id から作る)。
 * @returns 整形済みのラベル。
 */
export function sourceLabel(
  t: TFunction,
  id: string,
  source: BlockSourceInfo | null | undefined,
): string {
  if (source?.kind === "workspace" || (!source && id === WORKSPACE_SOURCE_ID)) {
    return t("palette.user.workspace");
  }
  const raw = source?.label ?? id.replace(SOURCE_ID_PREFIX, "");
  return cleanServerText(raw, MAX_LABEL_CHARS) || cleanServerText(id, MAX_LABEL_CHARS);
}

/**
 * セクション見出しのツールチップ (複数行、``title`` 属性用)。
 *
 * @param t - i18next の ``t``。
 * @param label - 見出しラベル (``sourceLabel`` の結果)。
 * @param source - ``sources[]`` の情報 (``null`` ならラベルだけ)。
 * @returns 改行区切りの文字列。
 */
export function sourceTooltip(
  t: TFunction,
  label: string,
  source: BlockSourceInfo | null,
): string {
  const lines = [label];
  if (source === null) return label;
  if (source.from_cwd) lines.push(t("palette.user.tooltip.cwd"));
  const root = cleanServerText(source.root, MAX_PATH_CHARS);
  if (root) lines.push(t("palette.user.tooltip.root", { root }));
  if (source.kind === "module") {
    lines.push(t("palette.user.tooltip.restart"));
    return lines.join("\n");
  }
  const files = source.files ?? [];
  if (files.length === 0) {
    lines.push(t("palette.user.tooltip.no_files"));
    return lines.join("\n");
  }
  lines.push(t("palette.user.tooltip.files", { count: files.length }));
  for (const f of files.slice(0, MAX_TOOLTIP_FILES)) {
    const path = cleanServerText(f.path, MAX_PATH_CHARS);
    lines.push(
      f.status === "error"
        ? `  ${t("palette.user.tooltip.file_error", { path })}`
        : `  ${path}`,
    );
  }
  if (files.length > MAX_TOOLTIP_FILES) {
    lines.push(
      `  ${t("palette.user.tooltip.more_files", { count: files.length - MAX_TOOLTIP_FILES })}`,
    );
  }
  return lines.join("\n");
}
