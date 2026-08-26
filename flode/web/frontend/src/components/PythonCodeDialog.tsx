// SPEC-0023 / ADR-0073: PythonFunction のコード編集ダイアログ。
//
// - 等幅 textarea (Tab で 4 スペース挿入)。ハイライト / 行番号は無し
//   (ADR-0023 bundle 予算、新規依存ゼロ)
// - 「適用」で introspect API に投げ、失敗なら行番号付き inline error を出して
//   **閉じない**。成功なら解析結果を cache に投入してから ``onApply(code)``
//   (= updateBlockParams 側の剪定判定が確定値で動く、ADR-0073 V10)
// - サーバは exec しないので、ここで任意コードを送っても実行はされない

import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { introspectPythonFunctions } from "../api/client";
import { putPythonSpec } from "../lib/pythonFunctionSpec";
import type { PythonFunctionSpec } from "../types/api";
import {
  DialogFooter,
  DialogShell,
  INPUT_MONO_CLS,
  PrimaryButton,
  SecondaryButton,
} from "./ui/inspector";

const TAB_INSERT = "    ";

interface PythonCodeDialogProps {
  initialCode: string;
  onApply: (code: string, spec: PythonFunctionSpec) => void;
  onClose: () => void;
}

export function PythonCodeDialog({
  initialCode,
  onApply,
  onClose,
}: PythonCodeDialogProps): JSX.Element {
  const { t } = useTranslation();
  const [code, setCode] = useState<string>(initialCode);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = useCallback(async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const resp = await introspectPythonFunctions([{ key: "k", code }]);
      const result = resp.results.k;
      if (result === undefined) {
        setError(t("python_function.dialog.network_error", { message: "empty response" }));
        return;
      }
      putPythonSpec(code, result);
      if (!result.resolved) {
        const { lineno, message } = result.error;
        setError(
          lineno !== null
            ? t("python_function.dialog.error_at", { lineno, message })
            : message,
        );
        return;
      }
      onApply(code, result);
    } catch (e) {
      setError(
        t("python_function.dialog.network_error", {
          message: e instanceof Error ? e.message : String(e),
        }),
      );
    } finally {
      setBusy(false);
    }
  }, [code, onApply, t]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const ta = e.currentTarget;
    const { selectionStart, selectionEnd } = ta;
    const next = code.slice(0, selectionStart) + TAB_INSERT + code.slice(selectionEnd);
    setCode(next);
    requestAnimationFrame(() => {
      ta.selectionStart = ta.selectionEnd = selectionStart + TAB_INSERT.length;
    });
  };

  return (
    <DialogShell
      title={t("python_function.dialog.title")}
      width="w-[640px]"
      onClose={onClose}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onClose} testId="python-code-cancel">
                {t("python_function.dialog.cancel")}
              </SecondaryButton>
              <PrimaryButton
                onClick={() => void apply()}
                disabled={busy}
                testId="python-code-apply"
              >
                {t("python_function.dialog.apply")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="flex flex-col gap-1 px-3 py-2">
        <textarea
          value={code}
          rows={18}
          spellCheck={false}
          wrap="off"
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={onKeyDown}
          data-testid="python-code-textarea"
          aria-label={t("python_function.dialog.title")}
          className={`${INPUT_MONO_CLS} h-[360px] w-full resize-y overflow-auto whitespace-pre`}
        />
        {error !== null && (
          <div
            role="alert"
            data-testid="python-code-error"
            className="border border-rose-300 bg-rose-50 px-2 py-1 font-mono text-[11px] text-rose-700 whitespace-pre-wrap"
          >
            {error}
          </div>
        )}
        <p className="text-[10px] leading-snug text-slate-500">
          {t("python_function.security_hint")}
        </p>
      </div>
    </DialogShell>
  );
}
