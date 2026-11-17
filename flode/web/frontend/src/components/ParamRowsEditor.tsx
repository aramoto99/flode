// ADR-0086 §6-B / SPEC-0037 U-1〜U-5: ユーザーブロックの行リスト引数の行エディタ (表 + ボタン列)。
//
// 行の正本は引数 (block.params、応答待ちの間は ParameterPanel の未確定値) で、表は値を持たない
// (描画のたび・操作のたびに読む)。describe はキュー経由で、行または他の引数が変わるたびに
// 300 ms のデバウンス、世代番号で古い応答を捨てる。取得中は直前の表示を保つ。
//
// 操作 (追加・編集・削除・↑・↓) は旧 → 新の対応表を作り、describe の ``ports`` が
// 入力 / 出力なら配線も付け替える (``onApply`` → ParameterPanel.applyParams)。
// 「テキストで編集…」と describe の失敗中は番号で対応 (``remaps = []``)。
//
// ``ports`` はブロックと引数で決まるので、成功した describe の値をこのエディタの間覚えておく
// (操作のたびに次の describe まで分からなくなり、ボタンがちらつくのを防ぐ)。最初の describe が
// 返るまで (失敗でもない間) は ``ports`` が分からず、番号で対応すると配線が別の行へずれるので、
// 既存の行を動かす操作 (編集・削除・↑・↓) を無効にする。末尾追加は既存の番号を変えないので有効。
//
// ダイアログの OK は、ポートの応答待ち (``busy``) の間は無効にして開いたままにする (入力を
// 黙って捨てない)。編集の OK は、開いた時点の行の文字列が今もその番号にあるときだけ当てる。

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { paramSearchErrorText } from "../lib/paramSearch";
import {
  appendRow,
  deleteRow,
  displayRows,
  PARAM_ROWS_CELL_CHARS,
  PARAM_ROWS_DEBOUNCE_MS,
  replaceRow,
  swapRows,
  toRemaps,
  type DescribedRows,
  type IndexRemap,
  type RowEdit,
} from "../lib/paramRows";
import { isParamRowsCancelled, paramRowsQueue, queueParamRows } from "../lib/paramRowsQueue";
import { cleanServerCell, cleanServerText, MAX_MESSAGE_CHARS } from "../lib/untrustedText";
import { stableJson } from "../lib/userBlockPorts";
import type { ParamRowsPorts } from "../types/api";
import { ParamRowDialog } from "./ParamRowDialog";
import { ParamRowsTextDialog } from "./ParamRowsTextDialog";
import { RowActionButton, RowTable, type RowTableRow } from "./ui/inspector";

/** ``ParamRowsEditor`` の props。 */
export interface ParamRowsEditorProps {
  /** ブロックの型 (``type_path``)。 */
  typePath: string;
  /** ブロック id (describe のスロットキーに使う)。 */
  blockId: string;
  /** 行エディタを宣言した引数名。 */
  param: string;
  /** 描画時点の行 (応答待ちの未確定値 → store → registry の既定値)。 */
  rows: ReadonlyArray<string>;
  /** 描画時点の他の引数値 (registry の既定値で補完、この引数自身は除く)。 */
  otherParams: Record<string, unknown>;
  /** ポートの応答待ち (操作ボタンをすべて無効にする。ADR-0086 §5-D)。 */
  busy: boolean;
  /** 操作の時点の行を読む (描画時の ``rows`` ではなく最新を使う)。 */
  readRows: () => string[];
  /** 要求を送る時点の他の引数値を読む。 */
  readParams: () => Record<string, unknown>;
  /** 新しい行と対応表を確定する (1 操作 = 1 Undo)。 */
  onApply: (rows: string[], remaps: IndexRemap[]) => void;
}

/**
 * 開いているダイアログ。編集 (``index`` が数) は開いた時点の行の文字列 (``original``) を持つ
 * (OK の時点でその番号の行が変わっていたら当てない)。
 */
type OpenDialog =
  | { kind: "row"; index: null }
  | { kind: "row"; index: number; original: string }
  | { kind: "text" }
  | null;

/**
 * 行リスト引数の表 + ボタン列。
 *
 * @param props - {@link ParamRowsEditorProps}。
 */
export function ParamRowsEditor({
  typePath,
  blockId,
  param,
  rows,
  otherParams,
  busy,
  readRows,
  readParams,
  onApply,
}: ParamRowsEditorProps): JSX.Element {
  const { t } = useTranslation();
  const [described, setDescribed] = useState<DescribedRows | null>(null);
  const [describeError, setDescribeError] = useState<string | null>(null);
  // 最後に成功した describe の ports (未取得なら null。ports そのものの null と区別する)
  const [knownPorts, setKnownPorts] = useState<{ ports: ParamRowsPorts } | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const generationRef = useRef(0);
  const slot = `describe:${blockId}:${param}`;

  // describe: 行・他の引数が変わるたびにデバウンスして送る (古い応答は世代番号で捨てる)
  const requestKey = stableJson({ rows, otherParams });
  const latestRef = useRef({ rows, otherParams });
  latestRef.current = { rows, otherParams };
  useEffect(() => {
    generationRef.current += 1;
    const generation = generationRef.current;
    const reqRows = [...latestRef.current.rows];
    const params = latestRef.current.otherParams;
    const timer = setTimeout(() => {
      queueParamRows(slot, "table", {
        type_path: typePath,
        param,
        action: "describe",
        params,
        rows: reqRows,
      }).then(
        (result) => {
          if (generation !== generationRef.current) return;
          setDescribed({ requestRows: reqRows, result });
          setKnownPorts({ ports: result.ports });
          setDescribeError(null);
        },
        (err: unknown) => {
          if (isParamRowsCancelled(err) || generation !== generationRef.current) return;
          // D4: 表の上にエラー、各行は生の文字列 1 列 (ports は不明 = 番号で対応)
          setDescribed(null);
          setDescribeError(paramSearchErrorText(err));
        },
      );
    }, PARAM_ROWS_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [requestKey, slot, typePath, param]);

  // アンマウント (ブロックの切り替え・パネルが外れる) で待ち・受信をやめる
  useEffect(() => {
    return () => {
      generationRef.current += 1;
      paramRowsQueue.cancel(slot);
    };
  }, [slot]);

  // 開いている間に行が変わって編集中の行が範囲外になったら (Undo 等) ダイアログを閉じる
  useEffect(() => {
    if (dialog?.kind === "row" && dialog.index !== null && dialog.index >= rows.length) {
      setDialog(null);
    }
  }, [dialog, rows.length]);

  const shown = displayRows(rows, described);
  const columns = (shown.columns ?? [t("inspector.param_rows.raw_column")]).map((c) =>
    cleanServerText(c, PARAM_ROWS_CELL_CHARS),
  );
  const tableRows: RowTableRow[] = shown.rows.map((r) => ({
    cells: r.cells.map((c) => cleanServerCell(c, PARAM_ROWS_CELL_CHARS)),
    error: r.error === null ? null : cleanServerText(r.error, MAX_MESSAGE_CHARS),
    dim: r.dim,
  }));
  // 配線の付け替えに使う ports (describe の失敗中は null = 番号で対応。D4)
  const ports = describeError !== null ? null : (knownPorts?.ports ?? null);
  // 最初の describe 待ち: ports が分からないので既存の行を動かす操作はできない
  const portsPending = describeError === null && knownPorts === null;
  // 編集・削除・↑・↓ を止める条件
  const locked = busy || portsPending;
  const sel = selected !== null && selected < rows.length ? selected : null;

  const apply = (edit: RowEdit): void => {
    onApply(edit.rows, toRemaps(edit.map, ports));
    setSelected(edit.selected);
  };
  const withSelection = (fn: (current: string[], index: number) => RowEdit | null): void => {
    if (locked || sel === null) return;
    const current = readRows();
    if (sel >= current.length) return;
    const edit = fn(current, sel);
    if (edit !== null) apply(edit);
  };
  const openEdit = (index: number): void => {
    if (locked) return;
    const original = readRows()[index];
    if (original !== undefined) setDialog({ kind: "row", index, original });
  };

  const onDialogOk = (open: Extract<OpenDialog, { kind: "row" }>, row: string): void => {
    // 応答待ちの間は開いたまま (OK は無効で描かれる。入力を黙って捨てない)
    if (busy) return;
    setDialog(null);
    const current = readRows();
    if (open.index === null) apply(appendRow(current, row));
    // 開いた後にその番号の行が変わった (Undo 等) なら何も変えずに閉じる
    else if (current[open.index] === open.original) apply(replaceRow(current, open.index, row));
  };

  const tableLabel = t("inspector.param_rows.table_aria", { param });
  const idPrefix = `param-rows-${param}`;
  return (
    <div className="flex flex-col gap-1" data-testid={`${idPrefix}-editor`}>
      {describeError !== null && (
        <p
          role="alert"
          className="max-h-[48px] overflow-y-auto whitespace-pre-wrap break-words text-[10px] leading-snug text-rose-700"
          data-testid={`${idPrefix}-describe-error`}
        >
          {t("inspector.param_rows.describe_failed", {
            message: cleanServerText(describeError, MAX_MESSAGE_CHARS),
          })}
        </p>
      )}
      <RowTable
        columns={columns}
        rows={tableRows}
        selectedIndex={sel}
        onSelect={setSelected}
        onActivate={openEdit}
        emptyText={t("inspector.param_rows.empty")}
        testId={`${idPrefix}-table`}
        ariaLabel={tableLabel}
      />
      <div className="flex flex-wrap items-center gap-1">
        <RowActionButton
          onClick={() => setDialog({ kind: "row", index: null })}
          disabled={busy}
          testId={`${idPrefix}-add`}
        >
          {t("inspector.param_rows.add")}
        </RowActionButton>
        <RowActionButton
          onClick={() => {
            if (sel !== null) openEdit(sel);
          }}
          disabled={locked || sel === null}
          testId={`${idPrefix}-edit`}
        >
          {t("inspector.param_rows.edit")}
        </RowActionButton>
        <RowActionButton
          onClick={() => withSelection((cur, i) => deleteRow(cur, i))}
          disabled={locked || sel === null}
          tone="danger"
          testId={`${idPrefix}-delete`}
        >
          {t("inspector.param_rows.delete")}
        </RowActionButton>
        <RowActionButton
          onClick={() => withSelection((cur, i) => (i > 0 ? swapRows(cur, i, i - 1) : null))}
          disabled={locked || sel === null || sel === 0}
          ariaLabel={t("inspector.param_rows.move_up_aria")}
          testId={`${idPrefix}-up`}
        >
          {t("inspector.param_rows.move_up")}
        </RowActionButton>
        <RowActionButton
          onClick={() =>
            withSelection((cur, i) => (i < cur.length - 1 ? swapRows(cur, i, i + 1) : null))
          }
          disabled={locked || sel === null || sel === rows.length - 1}
          ariaLabel={t("inspector.param_rows.move_down_aria")}
          testId={`${idPrefix}-down`}
        >
          {t("inspector.param_rows.move_down")}
        </RowActionButton>
        <RowActionButton
          onClick={() => setDialog({ kind: "text" })}
          disabled={busy}
          testId={`${idPrefix}-text`}
        >
          {t("inspector.param_rows.edit_text")}
        </RowActionButton>
        {busy && (
          <span className="text-[10px] text-slate-500" data-testid={`${idPrefix}-busy`}>
            {t("inspector.param_rows.busy")}
          </span>
        )}
        {!busy && portsPending && (
          <span className="text-[10px] text-slate-500" data-testid={`${idPrefix}-ports-pending`}>
            {t("inspector.param_rows.ports_pending")}
          </span>
        )}
      </div>
      {dialog?.kind === "row" && (
        <ParamRowDialog
          typePath={typePath}
          param={param}
          index={dialog.index}
          busy={busy}
          readRows={readRows}
          readParams={readParams}
          onOk={(row) => onDialogOk(dialog, row)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "text" && (
        <ParamRowsTextDialog
          param={param}
          initialRows={readRows()}
          busy={busy}
          onOk={(next) => {
            // 応答待ちの間は開いたまま (OK は無効で描かれる)
            if (busy) return;
            setDialog(null);
            // D1: テキスト編集は行の対応が分からないので番号で対応
            onApply(next, []);
          }}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
