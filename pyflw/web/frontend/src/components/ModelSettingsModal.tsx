// v0.16.0: Model Settings ダイアログ。Simulink の "Configuration Parameters"
// (Ctrl+E) に相当。Stop time は toolbar 側で編集するため、ここでは solver /
// dt / rtol / atol / dt_base のみを扱う。
//
// 設計方針:
//   - draft state で編集中の値を保持し、Save ボタンで一括 commit (= Apply)。
//     これは Simulink の Configuration Parameters dialog の挙動 (= 即時反映で
//     はなく Apply ボタンで適用) に揃える。
//   - 不正値 (空 / NaN / 非正) は Save 時に弾いてエラー表示。
//   - dt_base は ``Auto`` (= null) と「明示数値」のラジオ的 toggle。
//     チェックボックスで「明示指定する」を ON にすると数値入力欄が出る。

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateSimulatorConfig, useAppStore } from "../store/appStore";
import type { SimulatorConfig } from "../types/api";
import { ModalShell } from "./Modal";

// scipy.integrate.solve_ivp が受け付ける method 名 (= ADR-0001 / simulator.py
// の docstring に列挙)。順序は「精度 / 用途別」の頻出順。
const SOLVER_OPTIONS = ["RK45", "RK23", "DOP853", "Radau", "BDF", "LSODA"] as const;

interface ModelSettingsModalProps {
  onClose: () => void;
}

export function ModelSettingsModal({
  onClose,
}: ModelSettingsModalProps): JSX.Element {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);

  // 開いた時点の simulator を draft に複製。**意図的に空 deps**: モーダルを
  // 開いた時点のスナップショットを保持し、Cancel で破棄できるようにする。
  // editingModel が外部 (= 別タブ) で更新されても draft は引き継がない。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const initial = useMemo<SimulatorConfig | null>(
    () => (editingModel ? { ...editingModel.simulator } : null),
    [],
  );

  const [solver, setSolver] = useState<string>(initial?.solver ?? "RK45");
  const [dtStr, setDtStr] = useState<string>(
    initial ? String(initial.dt) : "0.01",
  );
  const [rtolStr, setRtolStr] = useState<string>(
    initial ? String(initial.rtol) : "1e-3",
  );
  const [atolStr, setAtolStr] = useState<string>(
    initial ? String(initial.atol) : "1e-6",
  );
  const [dtBaseExplicit, setDtBaseExplicit] = useState<boolean>(
    initial?.dt_base != null,
  );
  const [dtBaseStr, setDtBaseStr] = useState<string>(
    initial?.dt_base != null ? String(initial.dt_base) : "0.01",
  );
  const [error, setError] = useState<string | null>(null);

  // Ctrl+Enter で Save 起動。``save`` は draft 値に依存して都度新しい関数になる
  // ため、useRef で「常に最新の save を呼ぶ」パターンに切り替えて、addEventListener
  // をマウント時 1 回だけに固定する (= 毎レンダー登録 / 解除のループを防ぐ)。
  const saveRef = useRef<() => void>(() => {});
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) saveRef.current();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const parsePositive = (s: string): number | null => {
    const v = Number(s);
    return Number.isFinite(v) && v > 0 ? v : null;
  };

  const save = (): void => {
    const dt = parsePositive(dtStr);
    if (dt === null) {
      setError(t("model_settings.invalid_number", { name: t("model_settings.dt") }));
      return;
    }
    const rtol = parsePositive(rtolStr);
    if (rtol === null) {
      setError(
        t("model_settings.invalid_number", { name: t("model_settings.rtol") }),
      );
      return;
    }
    const atol = parsePositive(atolStr);
    if (atol === null) {
      setError(
        t("model_settings.invalid_number", { name: t("model_settings.atol") }),
      );
      return;
    }
    let dtBase: number | null = null;
    if (dtBaseExplicit) {
      const v = parsePositive(dtBaseStr);
      if (v === null) {
        setError(
          t("model_settings.invalid_number", {
            name: t("model_settings.dt_base"),
          }),
        );
        return;
      }
      dtBase = v;
    }
    updateSimulatorConfig({
      solver,
      dt,
      rtol,
      atol,
      dt_base: dtBase,
    });
    onClose();
  };
  // ``saveRef`` を毎 render で最新の ``save`` で更新する。useEffect の deps を
  // 入れない (= effect 後コミット済 ref 更新 = 同期的書き込みでも問題ない)。
  saveRef.current = save;

  if (!editingModel) {
    return (
      <ModalShell title={t("model_settings.title")} onClose={onClose}>
        <div className="p-6 text-sm text-slate-600">
          {t("model_settings.no_model")}
        </div>
      </ModalShell>
    );
  }

  // 入力共通: 高さ・余白・フォントサイズを統一して安定感を出す。
  const baseInput =
    "h-9 w-full rounded-md border border-slate-300 bg-white px-3 text-[13px] text-slate-800 transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20";

  return (
    <ModalShell
      title={t("model_settings.title")}
      onClose={onClose}
      width="w-[520px]"
    >
      {/* description: 上部にバナー風セクション */}
      <div className="border-b border-slate-200 bg-slate-50 px-6 py-3">
        <p className="text-[12px] leading-relaxed text-slate-600">
          {t("model_settings.description")}
        </p>
      </div>

      {/* main: label 上 / 入力 中 / hint 下 の縦レイアウト */}
      <div className="flex flex-col gap-5 px-6 py-5">
        <Field
          htmlFor="model-settings-solver"
          label={t("model_settings.solver")}
          hint={t("model_settings.solver_hint")}
        >
          <select
            id="model-settings-solver"
            value={solver}
            onChange={(e) => setSolver(e.target.value)}
            data-testid="model-settings-solver"
            className={baseInput}
          >
            {SOLVER_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>

        <Field
          htmlFor="model-settings-dt"
          label={t("model_settings.dt")}
          hint={t("model_settings.dt_hint")}
        >
          <NumberInput
            id="model-settings-dt"
            value={dtStr}
            onChange={setDtStr}
            testId="model-settings-dt"
          />
        </Field>

        {/* rtol / atol は対になる科学的許容誤差なので 2 列にして節約 */}
        <div className="grid grid-cols-2 gap-4">
          <Field htmlFor="model-settings-rtol" label={t("model_settings.rtol")}>
            <NumberInput
              id="model-settings-rtol"
              value={rtolStr}
              onChange={setRtolStr}
              testId="model-settings-rtol"
            />
          </Field>
          <Field htmlFor="model-settings-atol" label={t("model_settings.atol")}>
            <NumberInput
              id="model-settings-atol"
              value={atolStr}
              onChange={setAtolStr}
              testId="model-settings-atol"
            />
          </Field>
        </div>

        <Field
          htmlFor="model-settings-dt-base-auto"
          label={t("model_settings.dt_base")}
          hint={t("model_settings.dt_base_hint")}
        >
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-[13px] text-slate-700">
              <input
                id="model-settings-dt-base-auto"
                type="checkbox"
                checked={!dtBaseExplicit}
                onChange={() => setDtBaseExplicit((v) => !v)}
                data-testid="model-settings-dt-base-auto"
                className="h-4 w-4 cursor-pointer accent-blue-600"
              />
              <span>{t("model_settings.dt_base_auto")}</span>
            </label>
            {dtBaseExplicit && (
              <div className="flex-1">
                <NumberInput
                  id="model-settings-dt-base"
                  value={dtBaseStr}
                  onChange={setDtBaseStr}
                  testId="model-settings-dt-base"
                  ariaLabel={t("model_settings.dt_base")}
                />
              </div>
            )}
          </div>
        </Field>

        {error && (
          <div
            role="alert"
            className="rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-[12px] text-rose-700"
          >
            {error}
          </div>
        )}
      </div>

      {/* footer: bg-slate-50 でセクション区切り、ボタンを一回り大きく */}
      <div className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-6 py-3">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-4 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
        >
          {t("model_settings.button.cancel")}
        </button>
        <button
          type="button"
          onClick={save}
          data-testid="model-settings-save"
          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1"
        >
          {t("model_settings.button.save")}
        </button>
      </div>
    </ModalShell>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  /** ラベルが指す入力要素の id (= explicit ``<label htmlFor>``)。 */
  htmlFor: string;
  children: React.ReactNode;
}

function Field({ label, hint, htmlFor, children }: FieldProps): JSX.Element {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={htmlFor}
        className="text-[13px] font-semibold text-slate-800"
      >
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-[11px] leading-relaxed text-slate-500">{hint}</p>
      )}
    </div>
  );
}

interface NumberInputProps {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  testId?: string;
  ariaLabel?: string;
}

function NumberInput({
  id,
  value,
  onChange,
  testId,
  ariaLabel,
}: NumberInputProps): JSX.Element {
  return (
    <input
      id={id}
      aria-label={ariaLabel}
      type="text"
      inputMode="decimal"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      data-testid={testId}
      className="h-9 w-full rounded-md border border-slate-300 bg-white px-3 font-mono text-[13px] tabular-nums text-slate-800 transition-colors focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
    />
  );
}
