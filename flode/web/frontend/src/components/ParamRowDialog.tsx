// ADR-0086 §6-C / SPEC-0037 U-6〜U-9: 行リスト引数の 1 行を組み立てる編集ダイアログ。
//
// - 開くときに form (編集なら今の行、追加なら null) を取り、種類・フィールドを描く
// - 種類が 2 つ以上のときだけ種類の select。切り替えたらフィールドを既定値で埋める
// - 値が変わるたびに 300 ms のデバウンスで compose → describe([row]) をプレビューに出す
//   (世代番号で古い応答を捨てる)
// - OK が有効なのは、最新の値の compose が成功し、プレビューの describe が済んでその行に
//   error が無いとき (describe そのものの失敗は警告だけで OK は有効 = D4)。ポートの応答待ち
//   (``busy``) の間は無効 (開いたまま待つ)
// - pick フィールドは ParamSearchController に「キューを通す検索関数」を渡して使う。選んだ値は
//   ダイアログの状態で、検索結果が変わっても消さない
//
// 要求はすべて ``dialog:<id>:…`` のスロットでキューに入れ (表の describe より優先)、閉じたら
// まとめて取り消す。

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  fieldValuesFor,
  MAX_PICK_VALUES,
  PARAM_ROWS_CELL_CHARS,
  PARAM_ROWS_DEBOUNCE_MS,
} from "../lib/paramRows";
import { isParamRowsCancelled, paramRowsQueue, queueParamRows } from "../lib/paramRowsQueue";
import {
  PARAM_SEARCH_LIMIT,
  ParamSearchController,
  paramSearchErrorText,
  type ParamSearchFn,
  type ParamSearchViewState,
} from "../lib/paramSearch";
import {
  cleanServerCell,
  cleanServerText,
  MAX_LABEL_CHARS,
  MAX_MESSAGE_CHARS,
} from "../lib/untrustedText";
import { stableJson } from "../lib/userBlockPorts";
import type {
  ParamRowsDescribedRow,
  ParamRowsField,
  ParamRowsFieldValue,
  ParamRowsVariant,
} from "../types/api";
import {
  DialogFooter,
  DialogShell,
  PrimaryButton,
  PropertyGrid,
  PropertyRow,
  PropertyStackRow,
  RowActionButton,
  RowTable,
  SecondaryButton,
  SectionDivider,
  SELECT_CLS,
  SelectableTable,
  TextInput,
  type SelectableTableRow,
} from "./ui/inspector";

/** variant / field / option のラベルの表示上限 (サーバの ``MAX_PARAM_ROWS_LABEL_CHARS``)。 */
const LABEL_CHARS = 100;
/** 組み立てた行の表示上限 (サーバの行の上限と同じ)。 */
const ROW_CHARS = 1000;
/** プロパティ行のラベル幅 (px)。 */
const LABEL_WIDTH = 120;

/** ダイアログの通し番号 (スロットキーを開いたダイアログごとに分ける)。 */
let dialogSeq = 0;

/** ``ParamRowDialog`` の props。 */
export interface ParamRowDialogProps {
  /** ブロックの型 (``type_path``)。 */
  typePath: string;
  /** 行エディタを宣言した引数名。 */
  param: string;
  /** 編集中の行の番号 (追加なら ``null``)。 */
  index: number | null;
  /** ポートの応答待ち (OK を無効にして開いたままにする。入力は捨てない)。 */
  busy?: boolean;
  /** 要求を送る時点の行を読む。 */
  readRows: () => string[];
  /** 要求を送る時点の他の引数値を読む。 */
  readParams: () => Record<string, unknown>;
  /** OK: 組み立てた行を確定する。 */
  onOk: (row: string) => void;
  /** キャンセル / × / Escape。何も変えない。 */
  onClose: () => void;
}

/** form の取得状態。 */
type FormState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; variants: ParamRowsVariant[] };

/** プレビューの状態。 */
type PreviewState =
  | { status: "pending" }
  | { status: "compose_error"; message: string }
  | {
      status: "composed";
      row: string;
      /** describe の待ち。 */
      describing: boolean;
      columns: string[];
      described: ParamRowsDescribedRow | null;
      /** describe そのものの失敗 (警告だけ。OK は有効)。 */
      describeError: string | null;
    };

/**
 * 行の編集ダイアログ。
 *
 * @param props - {@link ParamRowDialogProps}。
 */
export function ParamRowDialog({
  typePath,
  param,
  index,
  busy = false,
  readRows,
  readParams,
  onOk,
  onClose,
}: ParamRowDialogProps): JSX.Element {
  const { t } = useTranslation();
  const idRef = useRef<number | null>(null);
  if (idRef.current === null) {
    dialogSeq += 1;
    idRef.current = dialogSeq;
  }
  const prefix = `dialog:${idRef.current}:`;
  const [form, setForm] = useState<FormState>({ status: "loading" });
  const [variantId, setVariantId] = useState("");
  const [values, setValues] = useState<Record<string, ParamRowsFieldValue>>({});
  const [preview, setPreview] = useState<PreviewState>({ status: "pending" });
  const previewGenRef = useRef(0);
  // 読み出し関数は描画ごとに作り直されうるので、非同期処理からは最新を ref で読む
  const readRef = useRef({ readRows, readParams });
  readRef.current = { readRows, readParams };

  // 閉じたら、このダイアログの要求をまとめて取り消す
  useEffect(() => {
    return () => {
      previewGenRef.current += 1;
      paramRowsQueue.cancelPrefix(prefix);
    };
  }, [prefix]);

  // form: 開いた時点の行 (編集) / null (追加) を種類と値に分解してもらう
  useEffect(() => {
    let alive = true;
    const rows = readRef.current.readRows();
    const row = index === null ? null : (rows[index] ?? null);
    queueParamRows(`${prefix}form`, "dialog", {
      type_path: typePath,
      param,
      action: "form",
      params: readRef.current.readParams(),
      row,
    }).then(
      (res) => {
        if (!alive) return;
        const variant = res.variants.find((v) => v.id === res.variant) ?? res.variants[0];
        setForm({ status: "ready", variants: res.variants });
        setVariantId(variant?.id ?? "");
        setValues(variant !== undefined ? fieldValuesFor(variant, res.values) : {});
      },
      (err: unknown) => {
        if (!alive || isParamRowsCancelled(err)) return;
        setForm({ status: "error", message: paramSearchErrorText(err) });
      },
    );
    return () => {
      alive = false;
    };
    // 開いたときに 1 回だけ (行が変わって index が範囲外になったら呼ぶ側が閉じる)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const variants = form.status === "ready" ? form.variants : [];
  const variant = variants.find((v) => v.id === variantId);

  // プレビュー: 値が変わるたびに compose → describe([row])
  const valuesKey = stableJson(values);
  useEffect(() => {
    if (variant === undefined) return;
    previewGenRef.current += 1;
    const generation = previewGenRef.current;
    const current = (): boolean => generation === previewGenRef.current;
    setPreview({ status: "pending" });
    const sendValues = values;
    const timer = setTimeout(() => {
      const rows = readRef.current.readRows();
      if (index !== null && index >= rows.length) return; // 呼ぶ側が閉じる
      const params = readRef.current.readParams();
      const slot = `${prefix}preview`;
      queueParamRows(slot, "dialog", {
        type_path: typePath,
        param,
        action: "compose",
        params,
        variant: variant.id,
        values: sendValues,
        rows,
        index,
      }).then(
        (composed) => {
          if (!current()) return;
          setPreview({
            status: "composed",
            row: composed.row,
            describing: true,
            columns: [],
            described: null,
            describeError: null,
          });
          queueParamRows(slot, "dialog", {
            type_path: typePath,
            param,
            action: "describe",
            params,
            rows: [composed.row],
          }).then(
            (d) => {
              if (!current()) return;
              setPreview({
                status: "composed",
                row: composed.row,
                describing: false,
                columns: d.columns,
                described: d.rows[0] ?? null,
                describeError: null,
              });
            },
            (err: unknown) => {
              if (!current() || isParamRowsCancelled(err)) return;
              setPreview({
                status: "composed",
                row: composed.row,
                describing: false,
                columns: [],
                described: null,
                describeError: paramSearchErrorText(err),
              });
            },
          );
        },
        (err: unknown) => {
          if (!current() || isParamRowsCancelled(err)) return;
          setPreview({ status: "compose_error", message: paramSearchErrorText(err) });
        },
      );
    }, PARAM_ROWS_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // 値の中身 (valuesKey) と種類で送り直す
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [variant, valuesKey, typePath, param, index, prefix]);

  // pick フィールドの検索関数 (キューを通す。409 はキューが吸収する)
  const searchFns = useMemo(() => {
    const make =
      (field: string): ParamSearchFn =>
      (query, _current, signal) => {
        const slot = `${prefix}search:${field}`;
        const onAbort = (): void => paramRowsQueue.cancel(slot);
        signal.addEventListener("abort", onAbort, { once: true });
        return queueParamRows(slot, "dialog", {
          type_path: typePath,
          param,
          action: "search",
          params: readRef.current.readParams(),
          field,
          query,
          limit: PARAM_SEARCH_LIMIT,
        }).finally(() => signal.removeEventListener("abort", onAbort));
      };
    return make;
  }, [prefix, typePath, param]);

  const okEnabled =
    !busy &&
    preview.status === "composed" &&
    !preview.describing &&
    (preview.described === null || preview.described.error === null);
  const ok = (): void => {
    if (preview.status !== "composed" || !okEnabled) return;
    onOk(preview.row);
  };

  const setField = (key: string, value: ParamRowsFieldValue): void => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };
  const switchVariant = (id: string): void => {
    const next = variants.find((v) => v.id === id);
    if (next === undefined) return;
    setVariantId(id);
    setValues(fieldValuesFor(next));
  };

  const title =
    index === null
      ? t("inspector.param_rows.dialog_title_add", { param })
      : t("inspector.param_rows.dialog_title_edit", { param });
  return (
    <DialogShell
      title={title}
      width="w-[600px]"
      onClose={onClose}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onClose} testId="param-row-dialog-cancel">
                {t("inspector.param_rows.cancel")}
              </SecondaryButton>
              <PrimaryButton onClick={ok} disabled={!okEnabled} testId="param-row-dialog-ok">
                {t("inspector.param_rows.ok")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="flex max-h-[70vh] flex-col overflow-y-auto px-3 py-2">
        {form.status === "loading" && (
          <p className="text-[11px] text-slate-600" role="status" data-testid="param-row-dialog-loading">
            {t("inspector.param_rows.form_loading")}
          </p>
        )}
        {form.status === "error" && (
          <p
            role="alert"
            className="whitespace-pre-wrap break-words text-[11px] text-rose-700"
            data-testid="param-row-dialog-form-error"
          >
            {t("inspector.param_rows.form_failed", {
              message: cleanServerText(form.message, MAX_MESSAGE_CHARS),
            })}
          </p>
        )}
        {form.status === "ready" && variant !== undefined && (
          <PropertyGrid>
            {variants.length >= 2 && (
              <PropertyRow
                label={t("inspector.param_rows.variant")}
                labelWidth={LABEL_WIDTH}
                labelAlign="left"
              >
                <select
                  value={variant.id}
                  onChange={(e) => switchVariant(e.target.value)}
                  className={`${SELECT_CLS} min-w-0 flex-1`}
                  data-testid="param-row-dialog-variant"
                >
                  {variants.map((v) => (
                    <option key={v.id} value={v.id}>
                      {labelText(v.label, v.id)}
                    </option>
                  ))}
                </select>
              </PropertyRow>
            )}
            {variant.fields.map((field) => (
              <FieldEditor
                key={`${variant.id}\u0000${field.key}`}
                field={field}
                value={values[field.key]}
                onChange={(v) => setField(field.key, v)}
                search={searchFns(field.key)}
              />
            ))}
            <SectionDivider label={t("inspector.param_rows.preview")} />
            <PreviewView preview={preview} />
          </PropertyGrid>
        )}
      </div>
    </DialogShell>
  );
}

/** variant / field / option のラベル (空なら id)。 */
function labelText(label: string, fallback: string): string {
  const cleaned = cleanServerText(label, LABEL_CHARS);
  return cleaned !== "" ? cleaned : cleanServerText(fallback, LABEL_CHARS);
}

/** フィールド 1 つの入力。 */
function FieldEditor({
  field,
  value,
  onChange,
  search,
}: {
  field: ParamRowsField;
  value: ParamRowsFieldValue | undefined;
  onChange: (value: ParamRowsFieldValue) => void;
  search: ParamSearchFn;
}): JSX.Element {
  const label = labelText(field.label, field.key);
  const testId = `param-row-field-${field.key}`;
  if (field.kind === "pick") {
    return (
      <PropertyStackRow label={label} testId={testId}>
        <PickField
          fieldKey={field.key}
          label={label}
          value={Array.isArray(value) ? value : []}
          onChange={onChange}
          search={search}
        />
      </PropertyStackRow>
    );
  }
  if (field.kind === "choice") {
    const options = field.options ?? [];
    return (
      <PropertyRow label={label} labelWidth={LABEL_WIDTH} labelAlign="left">
        <select
          value={typeof value === "string" ? value : (options[0]?.value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          className={`${SELECT_CLS} min-w-0 flex-1`}
          data-testid={testId}
          aria-label={label}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {labelText(o.label, o.value)}
            </option>
          ))}
        </select>
      </PropertyRow>
    );
  }
  return (
    <PropertyRow label={label} labelWidth={LABEL_WIDTH} labelAlign="left">
      <TextInput
        value={typeof value === "string" ? value : ""}
        onChange={onChange}
        widthClass="min-w-0 flex-1"
        mono
        maxLength={ROW_CHARS}
        testId={testId}
        ariaLabel={label}
      />
    </PropertyRow>
  );
}

/**
 * pick フィールド: 検索欄 + チェック付きの候補表 + 選んだ項目の一覧 (外せる)。
 * 選んだ値はダイアログの状態で、検索結果が変わっても消さない (ADR-0086 §6-C)。
 */
function PickField({
  fieldKey,
  label,
  value,
  onChange,
  search,
}: {
  fieldKey: string;
  label: string;
  value: ReadonlyArray<string>;
  onChange: (value: string[]) => void;
  search: ParamSearchFn;
}): JSX.Element {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [view, setView] = useState<ParamSearchViewState>({
    pending: false,
    result: null,
    error: null,
    stale: false,
  });
  const composingRef = useRef(false);
  const queryRef = useRef("");
  const searchRef = useRef(search);
  searchRef.current = search;
  const controllerRef = useRef<ParamSearchController | null>(null);
  useEffect(() => {
    const controller = new ParamSearchController({
      search: (q, current, signal) => searchRef.current(q, current, signal),
      onState: setView,
    });
    controllerRef.current = controller;
    return () => {
      controller.dispose();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [fieldKey]);

  const result = view.result;
  const rows: SelectableTableRow[] = useMemo(
    () =>
      (result?.rows ?? []).map((r) => ({
        key: r.value,
        label: cleanServerText(r.value, MAX_LABEL_CHARS),
        cells: r.cells.map((c) => cleanServerCell(c, PARAM_ROWS_CELL_CHARS)),
      })),
    [result],
  );
  const columns = useMemo(
    () => (result?.columns ?? []).map((c) => cleanServerText(c, PARAM_ROWS_CELL_CHARS)),
    [result],
  );
  const selected = new Set(value);
  const full = value.length >= MAX_PICK_VALUES;
  const disabledKeys = new Set(full ? rows.filter((r) => !selected.has(r.key)).map((r) => r.key) : []);

  const toggle = (key: string): void => {
    if (selected.has(key)) onChange(value.filter((v) => v !== key));
    else if (!full) onChange([...value, key]);
  };

  const status =
    view.error !== null
      ? cleanServerText(view.error, MAX_MESSAGE_CHARS)
      : view.pending
        ? t("inspector.param_rows.pick_searching")
        : "";
  const emptyText =
    query.trim() === ""
      ? t("inspector.param_rows.pick_empty_query")
      : result !== null && result.rows.length === 0
        ? t("inspector.param_rows.pick_no_results")
        : undefined;

  return (
    <div className="flex flex-col gap-1">
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
          controllerRef.current?.setQuery(queryRef.current);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.nativeEvent.isComposing && !composingRef.current) {
            e.preventDefault();
            controllerRef.current?.submit(e.currentTarget.value);
          }
        }}
        widthClass="w-full"
        placeholder={t("inspector.param_rows.pick_query_placeholder")}
        ariaLabel={`${label}: ${t("inspector.param_rows.pick_query")}`}
        testId={`param-row-pick-${fieldKey}-query`}
      />
      {status !== "" && (
        <div
          className={`truncate text-[10px] ${view.error !== null ? "text-rose-700" : "text-slate-600"}`}
          role={view.error !== null ? "alert" : "status"}
          title={status}
        >
          {status}
        </div>
      )}
      <SelectableTable
        columns={columns}
        rows={rows}
        selected={selected}
        disabledKeys={disabledKeys}
        disabledTitle={t("inspector.param_rows.pick_limit", { count: MAX_PICK_VALUES })}
        onToggle={toggle}
        heightClass="h-[140px]"
        testId={`param-row-pick-${fieldKey}-table`}
        emptyText={emptyText}
        ariaLabel={label}
      />
      <div className="text-[10px] text-slate-600">
        {t("inspector.param_rows.pick_selected", { count: value.length })}
      </div>
      <ul
        className="max-h-[96px] overflow-y-auto border border-slate-300 bg-white"
        data-testid={`param-row-pick-${fieldKey}-selected`}
      >
        {value.length === 0 && (
          <li className="px-1.5 py-0.5 text-[11px] text-slate-500">
            {t("inspector.param_rows.pick_none")}
          </li>
        )}
        {value.map((v) => {
          const text = cleanServerText(v, PARAM_ROWS_CELL_CHARS);
          return (
            <li
              key={v}
              className="flex items-center gap-1 border-b border-slate-100 px-1.5 text-[11px] text-slate-800"
            >
              <span className="min-w-0 flex-1 truncate font-mono" title={text}>
                {text}
              </span>
              <RowActionButton
                icon="remove"
                onClick={() => onChange(value.filter((x) => x !== v))}
                ariaLabel={t("inspector.param_rows.pick_remove", { value: text })}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** プレビュー行 (組み立てた行・ブロックの説明・誤り)。 */
function PreviewView({ preview }: { preview: PreviewState }): JSX.Element {
  const { t } = useTranslation();
  if (preview.status === "pending") {
    return (
      <p className="text-[11px] text-slate-500" role="status" data-testid="param-row-preview-pending">
        {t("inspector.param_rows.preview_pending")}
      </p>
    );
  }
  if (preview.status === "compose_error") {
    return (
      <p
        role="alert"
        className="max-h-[64px] overflow-y-auto whitespace-pre-wrap break-words text-[11px] text-rose-700"
        data-testid="param-row-preview-error"
      >
        {t("inspector.param_rows.compose_failed", {
          message: cleanServerText(preview.message, MAX_MESSAGE_CHARS),
        })}
      </p>
    );
  }
  const rowText = cleanServerText(preview.row, ROW_CHARS);
  const described = preview.described;
  const rowError = described?.error ?? null;
  return (
    <div className="flex flex-col gap-1">
      <div
        className="truncate border border-slate-300 bg-slate-50 px-1.5 font-mono text-[11px] text-slate-800"
        title={rowText}
        data-testid="param-row-preview-row"
      >
        {rowText}
      </div>
      {described !== null && (
        <RowTable
          columns={preview.columns.map((c) => cleanServerText(c, PARAM_ROWS_CELL_CHARS))}
          rows={[
            {
              cells: described.cells.map((c) => cleanServerCell(c, PARAM_ROWS_CELL_CHARS)),
              error: rowError === null ? null : cleanServerText(rowError, MAX_MESSAGE_CHARS),
            },
          ]}
          selectedIndex={null}
          onSelect={() => undefined}
          heightClass="max-h-[60px]"
          testId="param-row-preview-table"
        />
      )}
      {rowError !== null && (
        <p
          role="alert"
          className="whitespace-pre-wrap break-words text-[11px] text-rose-700"
          data-testid="param-row-preview-row-error"
        >
          {t("inspector.param_rows.preview_row_error", {
            message: cleanServerText(rowError, MAX_MESSAGE_CHARS),
          })}
        </p>
      )}
      {preview.describeError !== null && (
        <p
          className="whitespace-pre-wrap break-words text-[11px] text-amber-700"
          data-testid="param-row-preview-describe-warning"
        >
          {t("inspector.param_rows.preview_describe_failed", {
            message: cleanServerText(preview.describeError, MAX_MESSAGE_CHARS),
          })}
        </p>
      )}
    </div>
  );
}
