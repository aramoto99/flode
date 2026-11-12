// SPEC-0032 §1.2 / §1.3 / §1.6 (ADR-0080): ライブラリ関連のダイアログ。
//
// - ``LibraryEntryDialog``: キャンバスのブロックをマイブロックに登録する / 登録済み
//   エントリの名前・説明・分類を編集する (同じフォームを再利用)。登録で同名があれば
//   「上書き / 別名で保存」の確認 (既定は別名) を挟んで再送する。
// - ``ImportLibraryDialog``: 取り込み前の確認 (dry-run の結果: Python コードを含む
//   エントリの一覧と警告・未知の型・名前の衝突)。
//
// いずれも ``ui/inspector.tsx`` の primitives だけで組む (ui-design-system 準拠)。

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  importLibrary,
  registerLibraryEntry,
  updateLibraryEntryMetadata,
} from "../api/client";
import {
  describeLibraryError,
  describeNameConflict,
  libraryErrorArgs,
  libraryErrorCode,
} from "../lib/libraryErrors";
import { LIBRARIES_QUERY_KEY } from "../lib/librariesQuery";
import type {
  BlockEntry,
  LibraryEntryMetadata,
  LibraryEntryMetadataPatch,
  LibraryImportReport,
  RegisterLibraryEntryRequest,
  UserLibraryEntryResponse,
} from "../types/api";
import {
  DialogFooter,
  DialogShell,
  NoticeBox,
  PrimaryButton,
  PropertyGrid,
  PropertyHint,
  PropertyRow,
  SecondaryButton,
  TextArea,
  TextInput,
} from "./ui/inspector";

// サーバ (library_store.py) の上限と同値。超過はサーバでも 422 になる。
const MAX_DISPLAY_NAME_CHARS = 64;
const MAX_DESCRIPTION_CHARS = 1000;
const MAX_CATEGORY_SUFFIX_CHARS = 64;

const LABEL_WIDTH = 96;
const CATEGORY_DATALIST_ID = "library-entry-category-options";

/** code point 数 (サーバの文字数上限と同じ数え方)。 */
function charCount(text: string): number {
  return [...text].length;
}

/** ``LibraryEntryDialog`` の用途。 */
export type LibraryEntryDialogTarget =
  | { kind: "register"; block: BlockEntry }
  | { kind: "edit"; entry: LibraryEntryMetadata };

/** 同名エントリの確認待ち状態 (409 ``library_entry_name_conflict`` の内容)。 */
interface NameConflict {
  entryId: string;
  revision: number;
  displayName: string;
}

/**
 * マイブロックへの登録 / 登録済みエントリのメタデータ編集ダイアログ。
 *
 * 成功時は libraries query を invalidate してから ``onDone`` を呼ぶ (閉じるのは呼び出し側)。
 * 失敗時は理由をダイアログ内に表示し、入力は保持する。
 *
 * @param target 登録するブロック、または編集するエントリ。
 * @param categories 既存の分類 (自由入力の候補として出す)。
 * @param onDone 成功時に、サーバの応答を渡して呼ぶ。
 * @param onClose キャンセル / Escape / 外側クリック。
 */
export function LibraryEntryDialog({
  target,
  categories,
  onDone,
  onClose,
}: {
  target: LibraryEntryDialogTarget;
  categories: readonly string[];
  onDone: (response: UserLibraryEntryResponse) => void;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const isEdit = target.kind === "edit";
  const [name, setName] = useState(
    target.kind === "edit" ? target.entry.display_name : target.block.id,
  );
  const [description, setDescription] = useState(
    target.kind === "edit" ? target.entry.description : "",
  );
  const [category, setCategory] = useState(
    target.kind === "edit" ? target.entry.category_suffix : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<NameConflict | null>(null);

  const trimmedName = name.trim();
  const nameLength = charCount(trimmedName);
  const nameInvalid = nameLength === 0 || nameLength > MAX_DISPLAY_NAME_CHARS;
  const descriptionTooLong = charCount(description.trim()) > MAX_DESCRIPTION_CHARS;
  const categoryTooLong = charCount(category.trim()) > MAX_CATEGORY_SUFFIX_CHARS;
  const canSubmit = !busy && !nameInvalid && !descriptionTooLong && !categoryTooLong;

  /** API を呼び、成功なら ``onDone``、失敗なら理由を表示する (どちらでも一覧は取り直す)。 */
  const run = async (call: () => Promise<UserLibraryEntryResponse>): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const response = await call();
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_QUERY_KEY });
      onDone(response);
    } catch (err) {
      if (libraryErrorCode(err) === "library_entry_name_conflict" && !isEdit) {
        const args = libraryErrorArgs(err);
        if (typeof args.entry_id === "string" && typeof args.revision === "number") {
          setConflict({
            entryId: args.entry_id,
            revision: args.revision,
            displayName:
              typeof args.display_name === "string" ? args.display_name : trimmedName,
          });
          return;
        }
      }
      // 別タブでの更新・削除などが原因なら、一覧を取り直せば次の操作は通る
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_QUERY_KEY });
      setConflict(null);
      setError(describeLibraryError(t, err));
    } finally {
      setBusy(false);
    }
  };

  const closeUnlessBusy = (): void => {
    if (!busy) onClose();
  };

  const submit = (extra: Partial<RegisterLibraryEntryRequest> = {}): void => {
    if (!canSubmit) return;
    if (target.kind === "edit") {
      const { entry } = target;
      const patch: LibraryEntryMetadataPatch = {};
      if (trimmedName !== entry.display_name) patch.display_name = trimmedName;
      if (description.trim() !== entry.description) patch.description = description.trim();
      if (category.trim() !== entry.category_suffix) patch.category_suffix = category.trim();
      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }
      void run(() => updateLibraryEntryMetadata(entry.id, patch));
      return;
    }
    const { block } = target;
    void run(() =>
      registerLibraryEntry({
        // top-level の由来 (provenance) は送らない (サーバも除去する、ADR-0080 §A3-4)
        block: { id: block.id, type: block.type, params: block.params },
        display_name: trimmedName,
        description: description.trim(),
        category_suffix: category.trim(),
        ...extra,
      }),
    );
  };

  if (conflict !== null) {
    return (
      <NameConflictDialog
        conflict={conflict}
        busy={busy}
        onOverwrite={() =>
          submit({
            overwrite_entry_id: conflict.entryId,
            expected_revision: conflict.revision,
          })
        }
        onSaveAsNew={() => submit({ save_as_new: true })}
        onClose={() => {
          if (!busy) setConflict(null);
        }}
      />
    );
  }

  return (
    <DialogShell
      title={t(isEdit ? "library.entry_dialog.title_edit" : "library.entry_dialog.title_register")}
      width="w-[440px]"
      // 通信中は閉じない (結果を受け取る前に閉じると、成功したのか分からなくなる)
      onClose={closeUnlessBusy}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton
                onClick={closeUnlessBusy}
                disabled={busy}
                testId="library-entry-cancel"
              >
                {t("modal.button.cancel")}
              </SecondaryButton>
              <PrimaryButton
                onClick={() => submit()}
                disabled={!canSubmit}
                testId="library-entry-submit"
              >
                {t(isEdit ? "library.entry_dialog.save" : "library.entry_dialog.register")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="bg-white px-3 py-2.5" data-testid="library-entry-dialog">
        <PropertyGrid>
          <PropertyRow label={t("library.entry_dialog.name")} labelWidth={LABEL_WIDTH}>
            <TextInput
              value={name}
              onChange={setName}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) submit();
              }}
              autoFocus
              widthClass="w-full"
              ariaLabel={t("library.entry_dialog.name")}
              testId="library-entry-name"
            />
          </PropertyRow>
          {nameInvalid && (
            <PropertyHint
              labelWidth={LABEL_WIDTH}
              text={t("library.entry_dialog.name_invalid", { max: MAX_DISPLAY_NAME_CHARS })}
              testId="library-entry-name-hint"
            />
          )}
          <PropertyRow label={t("library.entry_dialog.description")} labelWidth={LABEL_WIDTH}>
            <TextArea
              value={description}
              onChange={setDescription}
              ariaLabel={t("library.entry_dialog.description")}
              testId="library-entry-description"
            />
          </PropertyRow>
          {descriptionTooLong && (
            <PropertyHint
              labelWidth={LABEL_WIDTH}
              text={t("library.entry_dialog.too_long", { max: MAX_DESCRIPTION_CHARS })}
            />
          )}
          <PropertyRow label={t("library.entry_dialog.category")} labelWidth={LABEL_WIDTH}>
            <TextInput
              value={category}
              onChange={setCategory}
              listId={CATEGORY_DATALIST_ID}
              placeholder={t("library.entry_dialog.category_placeholder")}
              widthClass="w-full"
              ariaLabel={t("library.entry_dialog.category")}
              testId="library-entry-category"
            />
            <datalist id={CATEGORY_DATALIST_ID}>
              {categories.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </PropertyRow>
          {categoryTooLong && (
            <PropertyHint
              labelWidth={LABEL_WIDTH}
              text={t("library.entry_dialog.too_long", { max: MAX_CATEGORY_SUFFIX_CHARS })}
            />
          )}
          <PropertyRow label={t("library.entry_dialog.destination")} labelWidth={LABEL_WIDTH}>
            <span className="text-[11px] text-slate-600">{t("palette.my_blocks")}</span>
          </PropertyRow>
        </PropertyGrid>
        {error !== null && (
          <div className="mt-2">
            <NoticeBox tone="error" testId="library-entry-error">
              {error}
            </NoticeBox>
          </div>
        )}
      </div>
    </DialogShell>
  );
}

/**
 * 同名エントリがあるときの確認ダイアログ (SPEC-0032 §1.2-3)。
 * 既定 (Enter / 強調ボタン) は「別名で保存」。上書きは revision が +1 される。
 */
function NameConflictDialog({
  conflict,
  busy,
  onOverwrite,
  onSaveAsNew,
  onClose,
}: {
  conflict: NameConflict;
  busy: boolean;
  onOverwrite: () => void;
  onSaveAsNew: () => void;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  // Enter = 既定の「別名で保存」(ボタンに focus が無くても効くよう window で受ける)
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      // ``repeat``: 登録フォームで押した Enter の長押しが、開いた直後のこのダイアログで
      // 「別名で保存」を確定してしまわないようにする
      if (e.key !== "Enter" || e.repeat || busy) return;
      // ボタンに focus がある Enter はそのボタンの click に任せる (二重実行しない)
      if (e.target instanceof HTMLButtonElement) return;
      e.preventDefault();
      onSaveAsNew();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onSaveAsNew]);

  return (
    <DialogShell
      title={t("library.name_conflict.title")}
      width="w-[440px]"
      onClose={onClose}
      footer={
        <DialogFooter
          left={
            <SecondaryButton onClick={onClose} disabled={busy} testId="library-conflict-cancel">
              {t("modal.button.cancel")}
            </SecondaryButton>
          }
          right={
            <>
              <SecondaryButton
                onClick={onOverwrite}
                disabled={busy}
                testId="library-conflict-overwrite"
              >
                {t("library.name_conflict.overwrite", {
                  from: conflict.revision,
                  to: conflict.revision + 1,
                })}
              </SecondaryButton>
              <PrimaryButton
                onClick={onSaveAsNew}
                disabled={busy}
                testId="library-conflict-save-as-new"
              >
                {t("library.name_conflict.save_as_new")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div
        className="bg-white px-3 py-2.5 text-[11px] leading-snug text-slate-800"
        data-testid="library-name-conflict-dialog"
      >
        <p>{t("library.name_conflict.message", { name: conflict.displayName })}</p>
        <p className="mt-1 text-slate-600">{t("library.name_conflict.detail")}</p>
      </div>
    </DialogShell>
  );
}

/**
 * ライブラリ取り込みの確認ダイアログ (SPEC-0032 §1.6-2 / §1.6-3)。
 *
 * dry-run の結果を見せ、Python コードを含むエントリがあれば一覧と警告文を出す。
 * 名前の衝突・未知のブロック型があるときは理由を表示して確定できなくする。
 * 確定すると本番の取り込みを行い、成功時に libraries query を invalidate して
 * ``onImported`` を呼ぶ。
 *
 * @param filename 選択されたファイル名 (表示専用)。
 * @param content ファイル本文の文字列。
 * @param report dry-run の応答。
 * @param onImported 取り込み成功時に本番の応答を渡して呼ぶ。
 * @param onClose キャンセル / Escape / 外側クリック。
 */
export function ImportLibraryDialog({
  filename,
  content,
  report,
  onImported,
  onClose,
}: {
  filename: string;
  content: string;
  report: LibraryImportReport;
  onImported: (report: LibraryImportReport) => void;
  onClose: () => void;
}): JSX.Element {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = report.conflict !== null || report.unknown_types.length > 0;

  const closeUnlessBusy = (): void => {
    if (!busy) onClose();
  };

  const confirm = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const result = await importLibrary(content, { dryRun: false, filename });
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_QUERY_KEY });
      onImported(result);
    } catch (err) {
      void queryClient.invalidateQueries({ queryKey: LIBRARIES_QUERY_KEY });
      setError(describeLibraryError(t, err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogShell
      title={t("library.import_dialog.title")}
      width="w-[480px]"
      // 通信中は閉じない
      onClose={closeUnlessBusy}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton
                onClick={closeUnlessBusy}
                disabled={busy}
                testId="library-import-cancel"
              >
                {t("modal.button.cancel")}
              </SecondaryButton>
              <PrimaryButton
                onClick={() => void confirm()}
                disabled={busy || blocked}
                testId="library-import-confirm"
              >
                {t("library.import_dialog.confirm")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div
        className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto bg-white px-3 py-2.5"
        data-testid="library-import-dialog"
      >
        <PropertyGrid>
          <PropertyRow label={t("library.import_dialog.file")} labelWidth={LABEL_WIDTH}>
            <span className="truncate text-[11px] text-slate-800" title={filename}>
              {filename}
            </span>
          </PropertyRow>
          <PropertyRow label={t("library.import_dialog.library")} labelWidth={LABEL_WIDTH}>
            <span className="truncate text-[11px] text-slate-800">
              {report.library.display_name || report.library.name}
              <span className="ml-1 font-mono text-slate-500">({report.library.name})</span>
            </span>
          </PropertyRow>
          <PropertyRow label={t("library.import_dialog.entries")} labelWidth={LABEL_WIDTH}>
            <span className="text-[11px] tabular-nums text-slate-800">
              {report.library.entry_count}
            </span>
          </PropertyRow>
        </PropertyGrid>
        <p className="text-[10px] leading-snug text-slate-500">
          {t("library.import_dialog.read_only_note")}
        </p>
        {report.conflict !== null && (
          <NoticeBox tone="error" testId="library-import-conflict">
            {describeNameConflict(
              t,
              report.conflict.name,
              report.conflict.reason,
              report.conflict.conflicts_with,
            )}
          </NoticeBox>
        )}
        {report.unknown_types.length > 0 && (
          <NoticeBox tone="error" testId="library-import-unknown-types">
            {t("library.import_dialog.unknown_types", {
              types: report.unknown_types.join(", "),
            })}
          </NoticeBox>
        )}
        {report.python_entries.length > 0 && (
          <NoticeBox tone="warning" testId="library-import-python-warning">
            <p>
              {t("library.import_dialog.python_warning", {
                n: report.python_entries.length,
              })}
            </p>
            <ul className="mt-1 list-disc pl-4">
              {report.python_entries.map((entry) => (
                <li key={entry.id} data-testid={`library-import-python-${entry.id}`}>
                  {entry.display_name || entry.id}
                  {entry.python_block_paths.some((p) => p !== "") && (
                    <span className="ml-1 font-mono text-[10px]">
                      ({entry.python_block_paths.filter((p) => p !== "").join(", ")})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </NoticeBox>
        )}
        {error !== null && (
          <NoticeBox tone="error" testId="library-import-error">
            {error}
          </NoticeBox>
        )}
      </div>
    </DialogShell>
  );
}
