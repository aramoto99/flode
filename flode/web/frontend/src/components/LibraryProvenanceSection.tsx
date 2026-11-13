// SPEC-0032 §1.4-3 / §1.4-5 / §1.4-6 (ADR-0080 §A7): Inspector の由来表示と差し替え。
//
// ライブラリから配置した (またはライブラリに登録した) ブロックを選択したとき、
// 「由来: マイブロック / PID (rev 2)」と状態 (最新 / 更新あり / ライブラリより新しい版 /
// 由来先が見つかりません) を出す。更新ありのときは [差し替え] で、確認ダイアログを
// 経てライブラリの現在の版に置き換える。由来は情報であり、見つからなくてもエラーでは
// ない。
//
// 由来の文字列はモデルファイル由来、ライブラリの名前は取り込んだファイル由来で、
// どちらも他人から受け取りうる。テキストとしてだけ描画し、制御・書式文字を除いて
// 長さを切る。固定文言「マイブロック」を出すのは出所が ``user`` のライブラリだけで、
// それ以外は内部名を添える (表示名で「マイブロック」を名乗る取り込みライブラリを
// 見分けられるようにする)。

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { describeLibraryError, sanitizeDisplayText } from "../lib/libraryErrors";
import { useLibraryIndex } from "../lib/librariesQuery";
import {
  readProvenance,
  resolveProvenance,
  type ProvenanceStatus,
} from "../lib/libraryProvenance";
import type { ReplacementIssue } from "../lib/libraryReplacement";
import { replaceBlockFromLibrary } from "../lib/libraryReplacementFlow";
import { dialog } from "../lib/dialogService";
import { useAppStore } from "../store/appStore";
import { pushToast } from "../store/toastStore";
import type { BlockEntry, LibraryMetadata, Locale } from "../types/api";
import {
  DangerButton,
  DialogFooter,
  DialogShell,
  NoticeBox,
  PropertyGrid,
  PropertyRow,
  RowActionButton,
  SecondaryButton,
  SectionDivider,
} from "./ui/inspector";

const LABEL_WIDTH = 88;
const DIALOG_LABEL_WIDTH = 96;
/** 通知に列挙する名前 (引き継げなかった値・変わったポート) の最大件数。 */
const MAX_LISTED_NAMES = 8;
/** 列挙つきの通知を表示しておく時間 (ms)。読む量が多いので既定より長くする。 */
const DETAIL_TOAST_MS = 12000;
/** 画面に出す、モデルファイル / ライブラリファイル由来の文字列 1 つの最大長。 */
const MAX_NAME_CHARS = 64;

/** 由来先が解決できた状態 (差し替えの対象になりうる)。 */
type ResolvedStatus = Extract<ProvenanceStatus, { kind: "current" | "update" | "ahead" }>;

/** 信頼できない文字列を表示用に整える (制御・書式文字を除き、長さを切る)。 */
function displayText(text: string): string {
  return sanitizeDisplayText(text, MAX_NAME_CHARS);
}

/** 名前の一覧を「a, b, c ほか n 件」の形にまとめる。 */
function listNames(t: TFunction, names: readonly string[]): string {
  const shown = names.slice(0, MAX_LISTED_NAMES).map(displayText).join(", ");
  const rest = names.length - MAX_LISTED_NAMES;
  return rest > 0 ? t("library.and_more", { names: shown, n: rest }) : shown;
}

/** 差し替えを拒否した理由 1 件の文言。 */
function describeIssue(t: TFunction, issue: ReplacementIssue): string {
  switch (issue.kind) {
    case "input_missing":
      return t("library.replace.issue.input_missing", { index: issue.index });
    case "input_kind_changed":
      return t("library.replace.issue.input_kind_changed", {
        index: issue.index,
        from: issue.from,
        to: issue.to,
      });
    case "output_missing":
      return t("library.replace.issue.output_missing", { index: issue.index });
    case "spec_unavailable":
      return t(
        issue.side === "old"
          ? "library.replace.issue.spec_unavailable_old"
          : "library.replace.issue.spec_unavailable_new",
      );
    case "unsupported_type":
      return t("library.replace.issue.unsupported_type", { type: displayText(issue.type) });
  }
}

/** 表示名を ``lang`` で引く (無ければ既定の表示名、それも無ければ ``fallback``)。 */
function localName(
  obj: { display_name: string; display_name_i18n: Partial<Record<Locale, string>> },
  fallback: string,
  lang: Locale,
): string {
  return obj.display_name_i18n[lang] || obj.display_name || fallback;
}

/**
 * ライブラリの表示ラベル。出所が ``user`` のときだけ固定文言「マイブロック」。それ以外は
 * ファイルが名乗る表示名に、内部名 (registry 内で一意) を ``(name)`` で添える。
 */
function libraryLabel(t: TFunction, library: LibraryMetadata, lang: Locale): string {
  if (library.origin === "user") return t("palette.my_blocks");
  const shown = displayText(localName(library, library.name, lang));
  const name = displayText(library.name);
  return shown === name ? name : `${shown} (${name})`;
}

/** ライブラリの種別 (マイブロック / 取り込んだライブラリ / その他のライブラリ)。 */
function libraryKindLabel(t: TFunction, library: LibraryMetadata): string {
  if (library.origin === "user") return t("library.kind.user");
  if (library.origin === "imported") return t("library.kind.imported");
  return t("library.kind.other");
}

/** 由来先の表示 (「ライブラリ名 / エントリ名 (rev N)」) を作る。 */
function sourceText(
  t: TFunction,
  status: Exclude<ProvenanceStatus, { kind: "none" }>,
  lang: Locale,
): string {
  const { provenance } = status;
  if (status.kind === "missing") {
    return t("library.provenance.source", {
      library: displayText(provenance.library),
      entry: displayText(provenance.entry),
      revision: provenance.revision,
    });
  }
  return t("library.provenance.source", {
    library: libraryLabel(t, status.library, lang),
    entry: displayText(localName(status.entry, status.entry.id, lang)),
    revision: provenance.revision,
  });
}

/** 状態の文言 (最新 / 更新あり / ライブラリより新しい版 / 由来先が見つかりません)。 */
function statusText(t: TFunction, status: Exclude<ProvenanceStatus, { kind: "none" }>): string {
  switch (status.kind) {
    case "missing":
      return t("library.provenance.status.missing");
    case "current":
      return t("library.provenance.status.current");
    case "update":
      return t("library.provenance.status.update", {
        from: status.provenance.revision,
        to: status.entry.revision,
      });
    case "ahead":
      return t("library.provenance.status.ahead", {
        from: status.provenance.revision,
        to: status.entry.revision,
      });
  }
}

/**
 * Inspector の由来セクション。由来を持たないブロックでは何も描画しない。
 *
 * @param block 選択中のブロック (Subsystem 内部のブロックでも同じ表示)。
 */
export function LibraryProvenanceSection({ block }: { block: BlockEntry }): JSX.Element | null {
  // 由来の無いブロック (大多数) ではライブラリ一覧を購読しない
  if (readProvenance(block.provenance) === null) return null;
  return <ProvenanceRows block={block} />;
}

/** 由来を持つブロックの由来行と状態行 (ライブラリ一覧を購読して状態を解決する)。 */
function ProvenanceRows({ block }: { block: BlockEntry }): JSX.Element | null {
  const { t, i18n } = useTranslation();
  const lang: Locale = i18n.language.startsWith("ja") ? "ja" : "en";
  const { index, ready, failed } = useLibraryIndex();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<ResolvedStatus | null>(null);
  const status = resolveProvenance(block.provenance, index);
  if (status.kind === "none") return null;

  // 一覧がまだ無い間は「見つからない」と断定しない (取得中 / 取得失敗を区別して出す)
  const pendingText = failed
    ? t("library.provenance.status.unavailable")
    : t("library.provenance.status.checking");
  const canReplace = ready && (status.kind === "update" || status.kind === "ahead");

  const runReplace = async (confirmed: ResolvedStatus): Promise<void> => {
    if (busy) return;
    const state = useAppStore.getState();
    setBusy(true);
    try {
      const outcome = await replaceBlockFromLibrary({
        filePath: state.selectedFilePath,
        path: state.editingPath,
        blockId: block.id,
        provenance: confirmed.provenance,
        libraryName: confirmed.library.name,
      });
      switch (outcome.status) {
        case "applied": {
          const lines = [
            t("library.replace.done", { block: displayText(block.id), revision: outcome.revision }),
          ];
          if (outcome.notCarried.length > 0) {
            lines.push(t("library.replace.not_carried", { names: listNames(t, outcome.notCarried) }));
          }
          if (outcome.portNameChanges.length > 0) {
            lines.push(
              t("library.replace.port_names_changed", {
                names: listNames(t, outcome.portNameChanges),
              }),
            );
          }
          // 引き継げなかった値・ポート名の変化は黙って済ませず通知に列挙する
          pushToast(
            lines.length > 1
              ? { severity: "warning", message: lines.join("\n"), durationMs: DETAIL_TOAST_MS }
              : { severity: "success", message: lines[0]! },
          );
          break;
        }
        case "incompatible":
          await dialog.alert(
            [
              t("library.replace.rejected"),
              ...outcome.issues.map((issue) => `• ${describeIssue(t, issue)}`),
            ].join("\n"),
            { title: t("library.replace.title") },
          );
          break;
        case "stale":
          pushToast({ severity: "warning", message: t("library.replace.stale") });
          break;
        case "failed":
          pushToast({
            severity: "error",
            message: t("library.replace.failed", {
              message: describeLibraryError(t, outcome.error),
            }),
          });
          break;
      }
    } finally {
      setBusy(false);
    }
  };

  const source = sourceText(t, status, lang);
  const state = ready ? statusText(t, status) : pendingText;
  return (
    <div className="shrink-0 px-3 pt-2" data-testid="library-provenance-section">
      <PropertyGrid>
        <SectionDivider label={t("library.provenance.section")} />
        <PropertyRow label={t("library.provenance.label")} labelWidth={LABEL_WIDTH} labelAlign="left">
          <span
            className="min-w-0 truncate text-[11px] text-slate-800"
            title={source}
            data-testid="library-provenance-source"
          >
            {source}
          </span>
        </PropertyRow>
        <PropertyRow
          label={t("library.provenance.status_label")}
          labelWidth={LABEL_WIDTH}
          labelAlign="left"
          action={
            canReplace ? (
              <RowActionButton
                onClick={() => {
                  if (!busy && (status.kind === "update" || status.kind === "ahead")) {
                    setConfirming(status);
                  }
                }}
                disabled={busy}
                testId="library-provenance-replace"
              >
                {t("library.replace.action")}
              </RowActionButton>
            ) : undefined
          }
        >
          <span
            // 状態は省略せず折り返す (狭い Inspector でも revision が読めるように)
            className={`min-w-0 text-[11px] leading-snug ${
              ready && status.kind === "update" ? "font-medium text-amber-700" : "text-slate-600"
            }`}
            title={state}
            data-testid="library-provenance-status"
            data-status={ready ? status.kind : failed ? "unavailable" : "checking"}
          >
            {state}
          </span>
        </PropertyRow>
      </PropertyGrid>
      {confirming !== null && (
        <ReplaceConfirmDialog
          blockId={block.id}
          status={confirming}
          lang={lang}
          onCancel={() => setConfirming(null)}
          onConfirm={() => {
            const confirmed = confirming;
            setConfirming(null);
            void runReplace(confirmed);
          }}
        />
      )}
    </div>
  );
}

/**
 * 差し替えの確認ダイアログ (SPEC-0032 §1.4-6 / §1.4-8)。
 *
 * 判断材料として、差し替え元 (ライブラリの表示名・内部名・種別・エントリ) と版を
 * 明記し、差し替え先が Python コードを含むなら警告する。内部で行った編集が失われる
 * ことを必ず示す。破壊的な操作なので Enter では確定せず、初期フォーカスはキャンセル。
 */
function ReplaceConfirmDialog({
  blockId,
  status,
  lang,
  onConfirm,
  onCancel,
}: {
  blockId: string;
  status: ResolvedStatus;
  lang: Locale;
  onConfirm: () => void;
  onCancel: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const valueCls = "min-w-0 break-words text-[11px] text-slate-800";
  return (
    <DialogShell
      title={t("library.replace.title")}
      width="w-[460px]"
      onClose={onCancel}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onCancel} autoFocus testId="library-replace-cancel">
                {t("modal.button.cancel")}
              </SecondaryButton>
              <DangerButton onClick={onConfirm} testId="library-replace-confirm">
                {t("library.replace.action")}
              </DangerButton>
            </>
          }
        />
      }
    >
      <div
        className="flex flex-col gap-2 bg-white px-3 py-2.5"
        data-testid="library-replace-dialog"
      >
        <PropertyGrid>
          <PropertyRow label={t("library.replace.block")} labelWidth={DIALOG_LABEL_WIDTH}>
            <span className={valueCls}>{displayText(blockId)}</span>
          </PropertyRow>
          <PropertyRow label={t("library.replace.source_library")} labelWidth={DIALOG_LABEL_WIDTH}>
            <span className={valueCls} data-testid="library-replace-source">
              {libraryLabel(t, status.library, lang)}
              {status.library.origin === "user" && (
                <span className="ml-1 font-mono text-slate-500">
                  ({displayText(status.library.name)})
                </span>
              )}
            </span>
          </PropertyRow>
          <PropertyRow label={t("library.replace.source_kind")} labelWidth={DIALOG_LABEL_WIDTH}>
            <span className={valueCls} data-testid="library-replace-kind">
              {libraryKindLabel(t, status.library)}
            </span>
          </PropertyRow>
          <PropertyRow label={t("library.replace.source_entry")} labelWidth={DIALOG_LABEL_WIDTH}>
            <span className={valueCls}>
              {displayText(localName(status.entry, status.entry.id, lang))}
            </span>
          </PropertyRow>
          <PropertyRow label={t("library.replace.revision")} labelWidth={DIALOG_LABEL_WIDTH}>
            <span className={`${valueCls} tabular-nums`}>
              {t("library.replace.revision_change", {
                from: status.provenance.revision,
                to: status.entry.revision,
              })}
            </span>
          </PropertyRow>
        </PropertyGrid>
        {status.entry.contains_python && (
          <NoticeBox tone="warning" testId="library-replace-python-warning">
            {t("library.replace.python_warning")}
          </NoticeBox>
        )}
        <p className="whitespace-pre-line text-[11px] leading-snug text-slate-800">
          {t("library.replace.confirm")}
        </p>
      </div>
    </DialogShell>
  );
}
