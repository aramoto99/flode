// ADR-0044 §論点 4 / §論点 7 / §論点 9: per-Scope プロット設定 dialog。
// gear ボタンから開かれ、Y/X 軸 / 凡例 / グリッド / per-signal 設定を編集する。
// 永続化先は ``editingModel.scope_settings[scopeId]`` (= モデル単位、ADR-0044 §論点 1)。

import { HexColorPicker } from "react-colorful";
import { useTranslation } from "react-i18next";

import { canUseLogScale, resolveSettings, resolveSignalColor } from "../lib/scopeSettings";
import { useAppStore } from "../store/appStore";
import { ModalShell } from "./Modal";

interface ScopeSettingsDialogProps {
  scopeId: string;
  onClose: () => void;
}

export function ScopeSettingsDialog({
  scopeId,
  onClose,
}: ScopeSettingsDialogProps): JSX.Element {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);
  const updateScopeSettings = useAppStore((s) => s.updateScopeSettings);
  const buffer = useAppStore((s) => s.scopes[scopeId]);

  const saved = editingModel?.scope_settings?.[scopeId];
  const settings = resolveSettings(saved);
  const nSignals = buffer?.n_signals ?? 0;
  const logSafe = canUseLogScale(buffer);

  return (
    <ModalShell
      title={t("scope.settings.title", "Plot Settings: {{id}}", { id: scopeId })}
      onClose={onClose}
      width="w-[480px]"
    >
      <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto p-4 text-[12px]">
        {/* Y axis */}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {t("scope.settings.section.y", "Y axis")}
          </legend>
          <div className="flex gap-2">
            {(["auto", "manual", "log"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => updateScopeSettings(scopeId, { y_mode: mode })}
                className={`rounded border px-2 py-1 text-[11px] ${settings.y_mode === mode ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}
              >
                {t(`scope.settings.y_mode.${mode}`, mode)}
              </button>
            ))}
          </div>
          {settings.y_mode === "log" && !logSafe && (
            <span className="text-[11px] text-amber-600">
              {t(
                "scope.warnings.log_fallback",
                "Some samples are zero/negative. Falling back to auto.",
              )}
            </span>
          )}
          {settings.y_mode === "manual" && (
            <div className="flex gap-2">
              <NumberField
                label={t("scope.settings.y_min", "Y min")}
                value={settings.y_min}
                onChange={(v) => updateScopeSettings(scopeId, { y_min: v })}
              />
              <NumberField
                label={t("scope.settings.y_max", "Y max")}
                value={settings.y_max}
                onChange={(v) => updateScopeSettings(scopeId, { y_max: v })}
              />
            </div>
          )}
        </fieldset>

        {/* X axis */}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {t("scope.settings.section.x", "X axis")}
          </legend>
          <div className="flex gap-2">
            {(["auto", "manual"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => updateScopeSettings(scopeId, { x_mode: mode })}
                className={`rounded border px-2 py-1 text-[11px] ${settings.x_mode === mode ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}
              >
                {t(`scope.settings.x_mode.${mode}`, mode)}
              </button>
            ))}
          </div>
          {settings.x_mode === "manual" && (
            <div className="flex gap-2">
              <NumberField
                label={t("scope.settings.x_min", "X min")}
                value={settings.x_min}
                onChange={(v) => updateScopeSettings(scopeId, { x_min: v })}
              />
              <NumberField
                label={t("scope.settings.x_max", "X max")}
                value={settings.x_max}
                onChange={(v) => updateScopeSettings(scopeId, { x_max: v })}
              />
            </div>
          )}
        </fieldset>

        {/* Legend */}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {t("scope.settings.section.legend", "Legend")}
          </legend>
          <div className="flex gap-2">
            {(["top", "bottom", "right", "off"] as const).map((pos) => (
              <button
                key={pos}
                type="button"
                onClick={() => updateScopeSettings(scopeId, { legend: pos })}
                className={`rounded border px-2 py-1 text-[11px] ${settings.legend === pos ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"}`}
              >
                {t(`scope.settings.legend.${pos}`, pos)}
              </button>
            ))}
          </div>
        </fieldset>

        {/* Grid */}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {t("scope.settings.section.grid", "Grid")}
          </legend>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.grid_major !== false}
              onChange={(e) =>
                updateScopeSettings(scopeId, { grid_major: e.target.checked })
              }
            />
            {t("scope.settings.grid.major", "Major grid")}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={settings.grid_minor === true}
              onChange={(e) =>
                updateScopeSettings(scopeId, { grid_minor: e.target.checked })
              }
            />
            {t("scope.settings.grid.minor", "Minor grid")}
          </label>
        </fieldset>

        {/* Per-signal */}
        {nSignals > 0 && (
          <fieldset className="flex flex-col gap-2">
            <legend className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
              {t("scope.settings.section.signals", "Signals")}
            </legend>
            {Array.from({ length: nSignals }, (_, i) => {
              const sigKey = String(i);
              const sig = settings.signals?.[sigKey];
              const color = resolveSignalColor(settings.signals, i);
              return (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-12 font-mono text-[11px]">[{i}]</span>
                  <ColorPickerInline
                    color={color}
                    onChange={(c) =>
                      updateScopeSettings(scopeId, {
                        signals: {
                          ...(settings.signals ?? {}),
                          [sigKey]: { ...(sig ?? {}), color: c },
                        },
                      })
                    }
                  />
                  <select
                    value={sig?.width ?? 1}
                    onChange={(e) =>
                      updateScopeSettings(scopeId, {
                        signals: {
                          ...(settings.signals ?? {}),
                          [sigKey]: {
                            ...(sig ?? {}),
                            width: Number(e.target.value) as 1 | 2 | 3,
                          },
                        },
                      })
                    }
                    className="rounded border border-slate-300 px-1 py-0.5 text-[11px]"
                  >
                    <option value={1}>1px</option>
                    <option value={2}>2px</option>
                    <option value={3}>3px</option>
                  </select>
                </div>
              );
            })}
          </fieldset>
        )}
      </div>
      <div className="flex justify-end border-t border-slate-100 bg-slate-50/50 px-3 py-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
        >
          {t("modal.button.close", "Close")}
        </button>
      </div>
    </ModalShell>
  );
}

interface NumberFieldProps {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}

function NumberField({ label, value, onChange }: NumberFieldProps): JSX.Element {
  return (
    <label className="flex flex-1 flex-col gap-0.5 text-[11px] text-slate-600">
      <span>{label}</span>
      <input
        type="text"
        inputMode="decimal"
        value={value === undefined ? "" : String(value)}
        onChange={(e) => {
          const v = e.target.value.trim();
          if (v === "") return onChange(undefined);
          const n = Number(v);
          if (Number.isFinite(n)) onChange(n);
        }}
        className="rounded border border-slate-300 px-1.5 py-0.5 font-mono"
      />
    </label>
  );
}

interface ColorPickerInlineProps {
  color: string;
  onChange: (color: string) => void;
}

function ColorPickerInline({ color, onChange }: ColorPickerInlineProps): JSX.Element {
  return (
    <details className="relative">
      <summary
        className="flex h-5 w-8 cursor-pointer list-none items-center justify-center rounded border border-slate-300"
        style={{ backgroundColor: color }}
        aria-label="Pick color"
      />
      <div className="absolute left-0 top-6 z-10">
        <HexColorPicker color={color} onChange={onChange} />
      </div>
    </details>
  );
}
