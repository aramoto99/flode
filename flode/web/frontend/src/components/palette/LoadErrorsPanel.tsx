// ADR-0081 §8-B 4. / §6-D: パレット最下部の「読み込みエラー」欄と「再読み込み」。
//
// - 折りたたみ (既定は閉)。エラー (``severity: "error"``) があれば件数を見出しに出す
// - 各行: 読み込み元・``path``:``line``・種別・メッセージ (``"info"`` は控えめに)
// - 読み込み元ごとの「読んだファイル」の一覧 (読んだファイルを必ず画面に出す、ADR-0081 §6)
// - ユーザーブロックを読まない設定 (非 loopback bind 等) なら理由を 1 行
// - 「再読み込み」ボタン (許可されていなければ無効化し、理由を tooltip に)
//
// サーバ由来の文字列はすべて ``cleanServerText`` で整形し、テキストノードとしてのみ描く。

import { useTranslation } from "react-i18next";

import { orderSources } from "../../lib/userBlocks";
import {
  cleanServerText,
  MAX_LABEL_CHARS,
  MAX_MESSAGE_CHARS,
  MAX_PATH_CHARS,
} from "../../lib/untrustedText";
import type {
  BlockLoadError,
  BlockRegistryResponse,
  BlockSourceInfo,
} from "../../types/api";
import { SecondaryButton } from "../ui/inspector";
import { sourceLabel } from "./sourceLabels";

/** ``load_errors[].kind`` の語彙 (ADR-0081 §8-A)。これ以外は整形した文字列のまま出す。 */
const KNOWN_LOAD_ERROR_KINDS = new Set(["syntax", "import", "spec", "conflict", "config"]);

/** 読み込みエラー 1 件の表示用の値 (整形済み)。 */
export interface LoadErrorRow {
  source: string;
  location: string;
  kind: string;
  message: string;
  info: boolean;
}

/**
 * 読み込みエラー 1 件を表示用に整形する (純粋関数、単体テスト用に公開)。
 *
 * @param error - ``load_errors[]`` の 1 件。
 * @param labelOf - 読み込み元 id → 見出しラベル。
 * @param kindLabel - 種別 → 表示文言。
 * @returns 整形済みの行。
 */
export function formatLoadError(
  error: BlockLoadError,
  labelOf: (id: string) => string,
  kindLabel: (kind: string) => string,
): LoadErrorRow {
  const path = cleanServerText(error.path, MAX_PATH_CHARS);
  const line =
    typeof error.line === "number" && Number.isInteger(error.line) && error.line > 0
      ? `:${error.line}`
      : "";
  const typePath = cleanServerText(error.type_path, MAX_PATH_CHARS);
  return {
    source: labelOf(typeof error.source === "string" ? error.source : ""),
    location: path ? `${path}${line}` : typePath,
    kind: kindLabel(cleanServerText(error.kind, MAX_LABEL_CHARS)),
    message: cleanServerText(error.message, MAX_MESSAGE_CHARS),
    info: error.severity === "info",
  };
}

/**
 * パレット最下部の読み込みエラー欄 + 再読み込み。
 *
 * @param registry - ``GET /blocks`` の応答 (``sources`` / ``load_errors`` / ``user_blocks``)。
 * @param onReload - 「再読み込み」の実行。
 * @param reloadPending - 再読み込み中か (ボタンを無効化する)。
 */
export function LoadErrorsPanel({
  registry,
  onReload,
  reloadPending,
}: {
  registry: BlockRegistryResponse;
  onReload: () => void;
  reloadPending: boolean;
}): JSX.Element {
  const { t } = useTranslation();
  const sources = orderSources(registry.sources ?? []);
  const errors = registry.load_errors ?? [];
  const status = registry.user_blocks;
  const sourceById = new Map<string, BlockSourceInfo>(sources.map((s) => [s.id, s]));
  const labelOf = (id: string): string => sourceLabel(t, id, sourceById.get(id));
  // 既知の種別だけ翻訳する (サーバの文字列を i18n キーの一部として使わない)
  const kindLabel = (kind: string): string =>
    KNOWN_LOAD_ERROR_KINDS.has(kind)
      ? t(`palette.load.kind.${kind}` as "palette.load.kind.syntax")
      : kind;
  const errorCount = errors.filter((e) => e.severity !== "info").length;
  const reloadAllowed = status?.reload_allowed === true;
  const reloadReason = reloadAllowed
    ? undefined
    : cleanServerText(status?.reload_reason, MAX_MESSAGE_CHARS) || undefined;

  return (
    <div
      className="shrink-0 border-t border-slate-200 bg-slate-50 px-2 py-1 text-[10px]"
      data-testid="palette-load-panel"
    >
      {status !== undefined && !status.enabled && (
        <div className="py-0.5 text-amber-700" data-testid="palette-user-blocks-disabled">
          {t("palette.user.disabled", {
            reason: cleanServerText(status.reason, MAX_MESSAGE_CHARS),
          })}
        </div>
      )}
      <details data-testid="palette-load-errors">
        <summary
          className={`cursor-pointer select-none py-0.5 text-[11px] ${
            errorCount > 0 ? "text-rose-700" : "text-slate-600"
          }`}
        >
          {errorCount > 0
            ? t("palette.load.title_count", { count: errorCount })
            : t("palette.load.title")}
        </summary>
        <div className="max-h-56 overflow-y-auto pb-1">
          {errors.length === 0 ? (
            <div className="py-0.5 text-slate-500">{t("palette.load.none")}</div>
          ) : (
            <ul>
              {errors.map((e, i) => {
                const row = formatLoadError(e, labelOf, kindLabel);
                return (
                  <li
                    // 同じ (source, path) に複数のエラーが出うるので index を併用する
                    key={`${row.source}:${row.location}:${i}`}
                    className="border-b border-slate-200 py-0.5"
                    data-testid="palette-load-error-row"
                    data-severity={row.info ? "info" : "error"}
                  >
                    <div className="flex flex-wrap items-baseline gap-x-1 text-slate-600">
                      <span className="font-semibold">{row.source}</span>
                      {row.location && <span className="font-mono">{row.location}</span>}
                      <span className="text-slate-500">
                        {row.info ? `${t("palette.load.info")} · ${row.kind}` : row.kind}
                      </span>
                    </div>
                    <div className={row.info ? "text-slate-500" : "text-rose-700"}>
                      {row.message}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {sources.length > 0 && (
            <div className="pt-1" data-testid="palette-load-files">
              <div className="font-semibold text-slate-600">{t("palette.load.files")}</div>
              {sources.map((s) => (
                <div key={s.id} className="py-0.5">
                  <div className="text-slate-600">{labelOf(s.id)}</div>
                  {(s.files ?? []).length === 0 ? (
                    <div className="pl-2 text-slate-400">{t("palette.load.files_none")}</div>
                  ) : (
                    (s.files ?? []).map((f) => (
                      <div key={f.path} className="truncate pl-2 font-mono text-slate-500">
                        {cleanServerText(f.path, MAX_PATH_CHARS)}
                        {f.status === "error" && (
                          <span className="pl-1 font-sans text-rose-700">
                            {t("palette.load.file_error")}
                          </span>
                        )}
                      </div>
                    ))
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </details>
      {status !== undefined && status.enabled && (
        <div className="flex justify-end py-0.5">
          <SecondaryButton
            onClick={onReload}
            disabled={!reloadAllowed || reloadPending}
            title={reloadReason}
            testId="palette-reload-button"
          >
            {reloadPending ? t("palette.reload.pending") : t("palette.reload.button")}
          </SecondaryButton>
        </div>
      )}
    </div>
  );
}
