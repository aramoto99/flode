// ADR-0085 §4-C / SPEC-0036: ユーザーブロックの引数に入れる値を検索して選ぶダイアログ。
//
// 検索語 → ブロックの検索関数が返す表 (列はブロックが決める) → 行を複数選ぶ →「追加」で
// 表の並び順に、既にある値を除いて引数の末尾に足す。値の正本は引数 (block.params、応答待ちの
// 間は ParameterPanel の未確定値) で、ダイアログは値を持たない (要求のたび・追加のたびに
// ``getCurrent`` で読む)。要求の制御 (デバウンス・直列化・古い応答の破棄・409 の再試行) は
// lib/paramSearch.ts のコントローラが持つ。

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { searchParamValues } from "../api/client";
import {
  appendUniqueValues,
  PARAM_SEARCH_LIMIT,
  ParamSearchController,
  type ParamSearchViewState,
} from "../lib/paramSearch";
import {
  cleanServerCell,
  cleanServerText,
  MAX_LABEL_CHARS,
  MAX_MESSAGE_CHARS,
} from "../lib/untrustedText";
import {
  DialogFooter,
  DialogShell,
  PrimaryButton,
  PropertyRow,
  SecondaryButton,
  SelectableTable,
  TextInput,
  type SelectableTableRow,
} from "./ui/inspector";

/**
 * セル・列見出しの表示上限 (文字数)。サーバ (ADR-0085 §3-B) も ``MAX_PARAM_SEARCH_CELL_CHARS`` /
 * 列見出し 200 字で切って返すので、ここは同じ値にしてサーバの切り詰めをそのまま見せる
 * (二重に短くしない)。サーバ側の値を変えたらここも揃える。
 */
const CELL_MAX_CHARS = 200;

/** ``ParamSearchDialog`` の props。 */
export interface ParamSearchDialogProps {
  /** ブロックの型 (``type_path``)。 */
  typePath: string;
  /** 検索を宣言した引数名。 */
  param: string;
  /** その時点の引数の値 (応答待ちの未確定値を含む)。要求・追加のたびに呼ぶ。 */
  getCurrent: () => string[];
  /** 「追加」: 新しい引数の値 (末尾に足したもの) を確定する。既存の引数編集と同じ経路で呼ぶ。 */
  onAppend: (next: string[]) => void;
  /** ダイアログを閉じる (閉じる・×・Escape・外側クリック)。走っている要求の受信はやめる。 */
  onClose: () => void;
}

/**
 * 引数の値の検索ダイアログ (SPEC-0036 U-2〜U-7)。
 *
 * @param props - {@link ParamSearchDialogProps}。
 */
export function ParamSearchDialog({
  typePath,
  param,
  getCurrent,
  onAppend,
  onClose,
}: ParamSearchDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<ParamSearchViewState>({
    pending: false,
    result: null,
    error: null,
    stale: false,
  });
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const composingRef = useRef(false);
  const queryRef = useRef("");
  // getCurrent は描画ごとに作り直されうるので、コントローラからは最新を ref で読む
  const getCurrentRef = useRef(getCurrent);
  getCurrentRef.current = getCurrent;

  const controllerRef = useRef<ParamSearchController | null>(null);
  useEffect(() => {
    const controller = new ParamSearchController({
      search: (q, current, signal) =>
        searchParamValues(
          { type_path: typePath, param, query: q, limit: PARAM_SEARCH_LIMIT, current },
          signal,
        ),
      getCurrent: () => getCurrentRef.current(),
      onState: setView,
    });
    controllerRef.current = controller;
    return () => {
      controller.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [typePath, param]);

  // 新しい結果が来たら選択を空にする (「表の並び順」は 1 つの表の中でしか定義できないため)
  const result = view.result;
  useEffect(() => {
    setSelected(new Set());
  }, [result]);

  const rows: SelectableTableRow[] = useMemo(
    () =>
      (result?.rows ?? []).map((r) => ({
        key: r.value,
        label: cleanServerText(r.value, MAX_LABEL_CHARS),
        cells: r.cells.map((c) => cleanServerCell(c, CELL_MAX_CHARS)),
      })),
    [result],
  );
  const columns = useMemo(
    () => (result?.columns ?? []).map((c) => cleanServerText(c, CELL_MAX_CHARS)),
    [result],
  );
  // 既に引数にある値の行は薄く・選べなくする (描画のたびに最新の値から作る)
  const current = getCurrent();
  const currentSet = new Set(current);
  // 追加後の再検索の応答待ち (古い提案) の間は、どの行も選べない
  const locked = view.stale;
  const disabledKeys = new Set(
    rows.filter((r) => locked || currentSet.has(r.key)).map((r) => r.key),
  );
  const selectable = locked ? [] : [...selected].filter((k) => !currentSet.has(k));

  const toggle = (key: string): void => {
    if (locked) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const append = (): void => {
    if (result === null || locked) return;
    const base = getCurrent();
    const next = appendUniqueValues(base, result.rows, selected);
    if (next.length > base.length) onAppend(next);
    setSelected(new Set());
    // current が変わったので、ブロックの提案 (衝突しない名前) も変わる
    controllerRef.current?.refresh();
  };

  const trimmed = query.trim();
  const status: { text: string; tone: "default" | "error" } | null =
    view.error !== null
      ? { text: cleanServerText(view.error, MAX_MESSAGE_CHARS), tone: "error" }
      : view.pending
        ? { text: t("inspector.param_search.searching"), tone: "default" }
        : result === null
          ? null
          : result.rows.length === 0
            ? { text: t("inspector.param_search.no_results"), tone: "default" }
            : result.truncated
              ? {
                  text: t("inspector.param_search.truncated", { count: result.rows.length }),
                  tone: "default",
                }
              : {
                  text: t("inspector.param_search.count", { count: result.rows.length }),
                  tone: "default",
                };
  const emptyText =
    trimmed === ""
      ? t("inspector.param_search.empty_query")
      : result !== null && result.rows.length === 0
        ? t("inspector.param_search.no_results")
        : undefined;

  const title = t("inspector.param_search.title", { param });
  return (
    <DialogShell
      title={title}
      width="w-[640px]"
      onClose={onClose}
      footer={
        <DialogFooter
          left={
            <span className="text-[11px] text-slate-600" data-testid="param-search-selected">
              {t("inspector.param_search.selected", { count: selectable.length })}
            </span>
          }
          right={
            <>
              <SecondaryButton onClick={onClose} testId="param-search-close">
                {t("inspector.param_search.close")}
              </SecondaryButton>
              <PrimaryButton
                onClick={append}
                disabled={selectable.length === 0}
                testId="param-search-add"
              >
                {t("inspector.param_search.add")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="flex flex-col gap-1 px-3 py-2">
        <PropertyRow label={t("inspector.param_search.query")} labelWidth={64} labelAlign="left">
          <TextInput
            value={query}
            onChange={(v) => {
              queryRef.current = v;
              setQuery(v);
              controllerRef.current?.setQuery(v, composingRef.current);
            }}
            onCompositionStart={() => {
              composingRef.current = true;
            }}
            onCompositionEnd={() => {
              composingRef.current = false;
              // 確定後の値で予約し直す (変換中の onChange では予約していない。ブラウザに
              // よって確定の onChange は compositionend の前にも後にも来る)
              controllerRef.current?.setQuery(queryRef.current);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && !composingRef.current) {
                e.preventDefault();
                controllerRef.current?.submit(e.currentTarget.value);
              }
            }}
            autoFocus
            widthClass="min-w-0 flex-1"
            placeholder={t("inspector.param_search.query_placeholder")}
            ariaLabel={title}
            testId="param-search-query"
          />
        </PropertyRow>
        <div
          className={`min-h-[16px] text-[11px] ${
            status?.tone === "error"
              ? "max-h-[64px] overflow-y-auto whitespace-pre-wrap break-words text-rose-700"
              : "truncate text-slate-600"
          }`}
          role={status?.tone === "error" ? "alert" : "status"}
          title={status?.text}
          data-testid="param-search-status"
        >
          {status?.text ?? ""}
        </div>
        <SelectableTable
          columns={columns}
          rows={rows}
          selected={selected}
          disabledKeys={disabledKeys}
          disabledTitle={
            locked
              ? t("inspector.param_search.searching")
              : t("inspector.param_search.already_added")
          }
          onToggle={toggle}
          testId="param-search-table"
          emptyText={emptyText}
          ariaLabel={title}
        />
      </div>
    </DialogShell>
  );
}
