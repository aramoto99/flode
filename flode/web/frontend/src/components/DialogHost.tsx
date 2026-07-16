// v0.32.0: dialogService の active dialog を購読して画面に描画する host。
//
// App.tsx の root に 1 つだけ mount すること。useSyncExternalStore で
// `getCurrentDialog` を購読、kind に応じて 3 種の dialog を切り替える。
//
// すべて inspector.tsx primitives (`DialogShell` / `PrimaryButton` /
// `SecondaryButton` / `DangerButton` / `INPUT_CLS`) を使う = Property
// Inspector 風の見た目 (= `.claude/docs/ui-design-system.md`)。

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";

import {
  type AlertOptions,
  type ConfirmOptions,
  type PendingDialog,
  type PromptOptions,
  getCurrentDialog,
  resolveCurrentDialog,
  subscribeDialog,
} from "../lib/dialogService";
import {
  DangerButton,
  DialogFooter,
  DialogShell,
  INPUT_CLS,
  PrimaryButton,
  SecondaryButton,
} from "./ui/inspector";

/**
 * 唯一の global dialog renderer。App ツリーの root に 1 つだけ mount する。
 */
export function DialogHost(): JSX.Element | null {
  const current = useSyncExternalStore(
    subscribeDialog,
    getCurrentDialog,
    getCurrentDialog,
  );
  if (!current) return null;
  switch (current.kind) {
    case "alert":
      return <AlertDialog key={dialogKey(current)} dialog={current} />;
    case "confirm":
      return <ConfirmDialog key={dialogKey(current)} dialog={current} />;
    case "prompt":
      return <PromptDialog key={dialogKey(current)} dialog={current} />;
    default:
      return null;
  }
}

/** dialog ごとに key を変えて remount させ、internal state (input value 等) を
 * 確実に reset させる。 */
function dialogKey(d: PendingDialog): string {
  // resolve 関数は dialog ごとにユニーク (= 各 Promise が新しい closure)。
  // 関数 identity を key に使うことで「次の dialog」で input state が初期化される。
  return String(d.resolve);
}

// ---------------------------------------------------------------------------
// AlertDialog
// ---------------------------------------------------------------------------

function AlertDialog({ dialog }: { dialog: PendingDialog }): JSX.Element {
  const { t } = useTranslation();
  const opts = dialog.options as AlertOptions;
  const close = (): void => resolveCurrentDialog(undefined);
  // Enter で OK
  useEffect(() => {
    const h = (e: KeyboardEvent): void => {
      if (e.key === "Enter") {
        e.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  return (
    <DialogShell
      title={opts.title ?? t("dialog.alert.title", "Notice")}
      width="w-[440px]"
      onClose={close}
      footer={
        <DialogFooter
          right={
            <PrimaryButton onClick={close}>
              {opts.okLabel ?? t("dialog.button.ok", "OK")}
            </PrimaryButton>
          }
        />
      }
    >
      <div className="whitespace-pre-line bg-white px-3 py-3 text-[12px] text-slate-800">
        {dialog.message}
      </div>
    </DialogShell>
  );
}

// ---------------------------------------------------------------------------
// ConfirmDialog
// ---------------------------------------------------------------------------

function ConfirmDialog({ dialog }: { dialog: PendingDialog }): JSX.Element {
  const { t } = useTranslation();
  const opts = dialog.options as ConfirmOptions;
  const onOk = (): void => resolveCurrentDialog(true);
  const onCancel = (): void => resolveCurrentDialog(false);
  // Enter で OK
  useEffect(() => {
    const h = (e: KeyboardEvent): void => {
      if (e.key === "Enter") {
        e.preventDefault();
        onOk();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const OkButton = opts.variant === "danger" ? DangerButton : PrimaryButton;
  return (
    <DialogShell
      title={opts.title ?? t("dialog.confirm.title", "Confirm")}
      width="w-[440px]"
      onClose={onCancel}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onCancel}>
                {opts.cancelLabel ?? t("dialog.button.cancel", "Cancel")}
              </SecondaryButton>
              <OkButton onClick={onOk}>
                {opts.okLabel ?? t("dialog.button.ok", "OK")}
              </OkButton>
            </>
          }
        />
      }
    >
      <div className="whitespace-pre-line bg-white px-3 py-3 text-[12px] text-slate-800">
        {dialog.message}
      </div>
    </DialogShell>
  );
}

// ---------------------------------------------------------------------------
// PromptDialog
// ---------------------------------------------------------------------------

function PromptDialog({ dialog }: { dialog: PendingDialog }): JSX.Element {
  const { t } = useTranslation();
  const opts = dialog.options as PromptOptions;
  const [value, setValue] = useState(opts.defaultValue ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  // mount 時に focus + 全選択 (= window.prompt のデフォルト挙動互換)
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    el.select();
  }, []);
  const onOk = (): void => resolveCurrentDialog(value);
  const onCancel = (): void => resolveCurrentDialog(null);
  return (
    <DialogShell
      title={opts.title ?? t("dialog.prompt.title", "Input")}
      width="w-[480px]"
      onClose={onCancel}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onCancel}>
                {opts.cancelLabel ?? t("dialog.button.cancel", "Cancel")}
              </SecondaryButton>
              <PrimaryButton onClick={onOk}>
                {opts.okLabel ?? t("dialog.button.ok", "OK")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="flex flex-col gap-2 bg-white px-3 py-3 text-[12px] text-slate-800">
        <div className="whitespace-pre-line">{dialog.message}</div>
        <input
          ref={inputRef}
          type="text"
          value={value}
          placeholder={opts.placeholder}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              onOk();
            }
          }}
          spellCheck={false}
          className={`${INPUT_CLS} h-6 w-full`}
        />
      </div>
    </DialogShell>
  );
}
