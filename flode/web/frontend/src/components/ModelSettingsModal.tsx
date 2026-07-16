// Model Settings ダイアログ (業界標準ブロック線図ツールの "Configuration Parameters" 相当)。
// Stop time は toolbar 側で編集するため、ここでは solver / dt / rtol / atol /
// dt_base のみを扱う。
//
// v0.25.0: ui/inspector.tsx primitives ベースに refactor、ScopeSettingsDialog と
// 同じ Property Inspector スタイル (= PropertyGrid + SectionDivider +
// DialogShell + native widgets) に統一。
//
// 設計方針:
//   - draft state で編集中の値を保持し、Save ボタンで一括 commit (= Apply)。
//     業界標準ブロック線図ツールの Configuration Parameters dialog の挙動 (= 即時反映ではなく
//     Apply で適用) に揃える。
//   - 不正値 (空 / NaN / 非正) は Save 時に弾いてエラー表示。
//   - dt_base は ``Auto`` (= null) と「明示数値」のチェックボックス toggle。

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateSimulatorConfig, useAppStore } from "../store/appStore";
import type { SimulatorConfig } from "../types/api";
import {
  CHECKBOX_CLS,
  DialogFooter,
  DialogShell,
  INPUT_MONO_CLS,
  PrimaryButton,
  PropertyGrid,
  PropertyHint,
  PropertyRow,
  SecondaryButton,
  SELECT_CLS,
  SectionDivider,
} from "./ui/inspector";

// scipy.integrate.solve_ivp が受け付ける method 名 (= ADR-0001 / simulator.py
// の docstring に列挙)。
const SOLVER_OPTIONS = [
  "RK45",
  "RK23",
  "DOP853",
  "Radau",
  "BDF",
  "LSODA",
] as const;

interface ModelSettingsModalProps {
  onClose: () => void;
}

export function ModelSettingsModal({
  onClose,
}: ModelSettingsModalProps): JSX.Element {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);

  // 開いた時点の simulator を draft に複製。意図的に空 deps (= モーダルを開いた
  // 時点のスナップショット、Cancel で破棄できる)。
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

  const parsePositive = (s: string): number | null => {
    const v = Number(s);
    return Number.isFinite(v) && v > 0 ? v : null;
  };

  const save = (): void => {
    const dt = parsePositive(dtStr);
    if (dt === null) {
      setError(
        t("model_settings.invalid_number", { name: t("model_settings.dt") }),
      );
      return;
    }
    const rtol = parsePositive(rtolStr);
    if (rtol === null) {
      setError(
        t("model_settings.invalid_number", {
          name: t("model_settings.rtol"),
        }),
      );
      return;
    }
    const atol = parsePositive(atolStr);
    if (atol === null) {
      setError(
        t("model_settings.invalid_number", {
          name: t("model_settings.atol"),
        }),
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
    updateSimulatorConfig({ solver, dt, rtol, atol, dt_base: dtBase });
    onClose();
  };

  // Ctrl+Enter で save (= save ref で最新の save を毎 render 更新)
  const saveRef = useRef<() => void>(() => {});
  saveRef.current = save;
  useEffect(() => {
    const handler = (e: KeyboardEvent): void => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) saveRef.current();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (!editingModel) {
    return (
      <DialogShell
        title={t("model_settings.title")}
        width="w-[480px]"
        onClose={onClose}
        footer={
          <DialogFooter
            right={<PrimaryButton onClick={onClose}>OK</PrimaryButton>}
          />
        }
      >
        <div className="bg-white p-6 text-[11px] text-slate-600">
          {t("model_settings.no_model")}
        </div>
      </DialogShell>
    );
  }

  return (
    <DialogShell
      title={t("model_settings.title")}
      width="w-[480px]"
      onClose={onClose}
      footer={
        <DialogFooter
          right={
            <>
              <SecondaryButton onClick={onClose}>
                {t("model_settings.button.cancel")}
              </SecondaryButton>
              <PrimaryButton onClick={save} testId="model-settings-save">
                {t("model_settings.button.save")}
              </PrimaryButton>
            </>
          }
        />
      }
    >
      <div className="h-[280px] overflow-y-auto bg-white px-3 py-2.5">
        <PropertyGrid>
          <SectionDivider
            label={t("model_settings.section.solver", "Solver")}
          />
          <PropertyRow label={t("model_settings.solver", "Method")}>
            <select
              value={solver}
              onChange={(e) => setSolver(e.target.value)}
              data-testid="model-settings-solver"
              className={`${SELECT_CLS} w-32`}
            >
              {SOLVER_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </PropertyRow>
          <PropertyHint
            testId="model-settings-solver-desc"
            text={t(`model_settings.solver_desc.${solver}`, "")}
          />

          <SectionDivider
            label={t("model_settings.section.step_size", "Step size")}
          />
          <PropertyRow label={t("model_settings.dt", "dt")}>
            <input
              type="text"
              inputMode="decimal"
              value={dtStr}
              onChange={(e) => setDtStr(e.target.value)}
              data-testid="model-settings-dt"
              className={`${INPUT_MONO_CLS} w-32`}
            />
          </PropertyRow>
          <PropertyRow
            label={t("model_settings.dt_base", "dt base")}
          >
            <label className="flex items-center gap-1.5 text-[11px] text-slate-700">
              <input
                type="checkbox"
                checked={!dtBaseExplicit}
                onChange={() => setDtBaseExplicit((v) => !v)}
                data-testid="model-settings-dt-base-auto"
                className={CHECKBOX_CLS}
              />
              <span>{t("model_settings.dt_base_auto", "Auto")}</span>
            </label>
          </PropertyRow>
          {dtBaseExplicit && (
            <PropertyRow
              indent
              label={t("model_settings.dt_base_value", "Value")}
            >
              <input
                type="text"
                inputMode="decimal"
                value={dtBaseStr}
                onChange={(e) => setDtBaseStr(e.target.value)}
                data-testid="model-settings-dt-base"
                aria-label={t("model_settings.dt_base", "dt base")}
                className={`${INPUT_MONO_CLS} w-32`}
              />
            </PropertyRow>
          )}

          <SectionDivider
            label={t("model_settings.section.tolerance", "Tolerance")}
          />
          <PropertyRow label={t("model_settings.rtol", "rtol")}>
            <input
              type="text"
              inputMode="decimal"
              value={rtolStr}
              onChange={(e) => setRtolStr(e.target.value)}
              data-testid="model-settings-rtol"
              className={`${INPUT_MONO_CLS} w-32`}
            />
          </PropertyRow>
          <PropertyRow label={t("model_settings.atol", "atol")}>
            <input
              type="text"
              inputMode="decimal"
              value={atolStr}
              onChange={(e) => setAtolStr(e.target.value)}
              data-testid="model-settings-atol"
              className={`${INPUT_MONO_CLS} w-32`}
            />
          </PropertyRow>

          {error && (
            <div
              role="alert"
              className="mt-2 border border-rose-300 bg-rose-50 px-2 py-1 text-[11px] text-rose-700"
            >
              {error}
            </div>
          )}
        </PropertyGrid>
      </div>
    </DialogShell>
  );
}
