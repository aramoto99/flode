// ADR-0086 §6-A / SPEC-0037 U-10: 行リスト引数の「テキストで編集…」ダイアログ。
//
// 1 行 1 項目 (引用符・JSON の書式なし)。OK で全行を置き換える (前後の空白を削り空行を捨てる)。
// 配線は行の対応が分からないので番号で対応する (D1。呼ぶ側が ``remaps = []`` で確定する)。

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { formatTextList, parseTextList } from "../lib/paramRows";
import {
  DialogFooter,
  DialogShell,
  PrimaryButton,
  SecondaryButton,
  TextListEditor,
} from "./ui/inspector";

/** ``ParamRowsTextDialog`` の props。 */
export interface ParamRowsTextDialogProps {
  /** 引数名 (タイトルに出す)。 */
  param: string;
  /** 開いた時点の行 (初期内容)。 */
  initialRows: ReadonlyArray<string>;
  /** ポートの応答待ち (OK を無効にして開いたままにする。入力は捨てない)。 */
  busy?: boolean;
  /** OK: 新しい行 (解析済み)。 */
  onOk: (rows: string[]) => void;
  /** キャンセル / × / Escape。何も変えない。 */
  onClose: () => void;
}

/**
 * 行リスト引数をテキストで編集するダイアログ。
 *
 * @param props - {@link ParamRowsTextDialogProps}。
 */
export function ParamRowsTextDialog({
  param,
  initialRows,
  busy = false,
  onOk,
  onClose,
}: ParamRowsTextDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [text, setText] = useState(() => formatTextList(initialRows));
  const parsed = parseTextList(text);
  const title = t("inspector.param_rows.text_title", { param });
  return (
    <DialogShell
      title={title}
      width="w-[560px]"
      onClose={onClose}
      footer={
        <DialogFooter
          left={
            <span className="text-[11px] text-slate-600" data-testid="param-rows-text-count">
              {t("inspector.param_rows.text_count", { count: parsed.length })}
            </span>
          }
          right={
            <>
              <SecondaryButton onClick={onClose} testId="param-rows-text-cancel">
                {t("inspector.param_rows.cancel")}
              </SecondaryButton>
              <PrimaryButton
                onClick={() => onOk(parsed)}
                disabled={busy}
                testId="param-rows-text-ok"
              >
                {t("inspector.param_rows.ok")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="flex flex-col gap-1 px-3 py-2">
        <p className="text-[10px] leading-snug text-slate-500">
          {t("inspector.param_rows.text_hint")}
        </p>
        <TextListEditor
          value={text}
          onChange={setText}
          autoFocus
          testId="param-rows-text-input"
          ariaLabel={title}
        />
      </div>
    </DialogShell>
  );
}
