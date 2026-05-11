// ADR-0044 §論点 4 / §論点 7 / §論点 9: per-Scope プロット設定 dialog。
// gear ボタンから開かれ、Y/X 軸 / 凡例 / グリッド / per-signal 設定を編集する。
// 永続化先は ``editingModel.scope_settings[scopeId]`` (= モデル単位、ADR-0044 §論点 1)。
//
// v0.24.3: UI を全面刷新 (= 旧 plain 版を「安っぽい」と指摘されたため)。
// 2 列グリッド・segmented control・switch toggle・hex 表示付き color picker。

import { useState } from "react";
import { HexColorPicker } from "react-colorful";
import { useTranslation } from "react-i18next";

import {
  canUseLogScale,
  resolveSettings,
  resolveSignalColor,
} from "../lib/scopeSettings";
import { useAppStore } from "../store/appStore";
import type { SignalMarker, SignalSettings } from "../types/api";
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
  const resetScopeSettings = useAppStore((s) => s.resetScopeSettings);
  const buffer = useAppStore((s) => s.scopes[scopeId]);

  const saved = editingModel?.scope_settings?.[scopeId];
  const settings = resolveSettings(saved);
  const nSignals = buffer?.n_signals ?? 0;
  const logSafe = canUseLogScale(buffer);

  const yModes = ["auto", "manual", "log"] as const;
  const xModes = ["auto", "manual"] as const;
  const legendPositions = ["top", "bottom", "right", "off"] as const;
  const markers: SignalMarker[] = ["none", "circle", "square", "cross"];

  return (
    <ModalShell
      title={t("scope.settings.title", "Plot Settings: {{id}}", { id: scopeId })}
      onClose={onClose}
      width="w-[600px]"
    >
      <div className="flex max-h-[75vh] flex-col overflow-y-auto">
        <div className="grid grid-cols-2 gap-3 p-4">
          {/* Y 軸 */}
          <Section
            icon={<IconAxisY />}
            title={t("scope.settings.section.y", "Y axis")}
          >
            <SegmentedControl
              value={settings.y_mode!}
              options={yModes.map((m) => ({
                value: m,
                label: t(`scope.settings.y_mode.${m}`, m),
              }))}
              onChange={(v) =>
                updateScopeSettings(scopeId, { y_mode: v as typeof yModes[number] })
              }
            />
            {settings.y_mode === "manual" && (
              <div className="mt-2 grid grid-cols-2 gap-2">
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
            {settings.y_mode === "log" && !logSafe && (
              <p className="mt-2 flex items-start gap-1 text-[11px] text-amber-700">
                <IconWarning />
                <span>
                  {t(
                    "scope.warnings.log_fallback",
                    "Some samples are zero/negative. Falling back to auto.",
                  )}
                </span>
              </p>
            )}
          </Section>

          {/* X 軸 */}
          <Section
            icon={<IconAxisX />}
            title={t("scope.settings.section.x", "X axis")}
          >
            <SegmentedControl
              value={settings.x_mode!}
              options={xModes.map((m) => ({
                value: m,
                label: t(`scope.settings.x_mode.${m}`, m),
              }))}
              onChange={(v) =>
                updateScopeSettings(scopeId, { x_mode: v as typeof xModes[number] })
              }
            />
            {settings.x_mode === "manual" && (
              <div className="mt-2 grid grid-cols-2 gap-2">
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
          </Section>

          {/* 凡例 */}
          <Section
            icon={<IconLegend />}
            title={t("scope.settings.section.legend", "Legend")}
          >
            <SegmentedControl
              value={settings.legend!}
              options={legendPositions.map((p) => ({
                value: p,
                label: t(`scope.settings.legend.${p}`, p),
              }))}
              onChange={(v) =>
                updateScopeSettings(scopeId, {
                  legend: v as typeof legendPositions[number],
                })
              }
            />
          </Section>

          {/* グリッド */}
          <Section
            icon={<IconGrid />}
            title={t("scope.settings.section.grid", "Grid")}
          >
            <div className="flex flex-col gap-1.5">
              <SwitchRow
                label={t("scope.settings.grid.major", "Major grid")}
                checked={settings.grid_major !== false}
                onChange={(c) =>
                  updateScopeSettings(scopeId, { grid_major: c })
                }
              />
              <SwitchRow
                label={t("scope.settings.grid.minor", "Minor grid")}
                checked={settings.grid_minor === true}
                onChange={(c) =>
                  updateScopeSettings(scopeId, { grid_minor: c })
                }
              />
            </div>
          </Section>
        </div>

        {/* 信号 (full-width) */}
        {nSignals > 0 && (
          <div className="border-t border-slate-200 px-4 py-3">
            <div className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              <IconSignal />
              <span>{t("scope.settings.section.signals", "Signals")}</span>
              <span className="text-slate-400">({nSignals})</span>
            </div>
            <div className="flex flex-col divide-y divide-slate-100 rounded border border-slate-200 bg-slate-50/50">
              {Array.from({ length: nSignals }, (_, i) => (
                <SignalRow
                  key={i}
                  scopeId={scopeId}
                  signalIdx={i}
                  signals={settings.signals}
                  totalSignals={nSignals}
                  markers={markers}
                  t={t}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/80 px-4 py-2.5">
        <button
          type="button"
          onClick={() => resetScopeSettings(scopeId)}
          className="rounded px-2.5 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-200 hover:text-slate-800"
        >
          {t("scope.settings.reset", "Reset to defaults")}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md bg-blue-600 px-3.5 py-1.5 text-xs font-medium text-white shadow-sm hover:bg-blue-700"
        >
          {t("modal.button.close", "Close")}
        </button>
      </div>
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Sub components
// ---------------------------------------------------------------------------

interface SectionProps {
  icon: JSX.Element;
  title: string;
  children: React.ReactNode;
}

function Section({ icon, title, children }: SectionProps): JSX.Element {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {icon}
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

interface SegmentedControlProps<T extends string> {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (v: T) => void;
}

function SegmentedControl<T extends string>({
  value,
  options,
  onChange,
}: SegmentedControlProps<T>): JSX.Element {
  return (
    <div className="inline-flex w-full overflow-hidden rounded-md border border-slate-300 bg-white">
      {options.map((opt, idx) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`flex-1 px-2 py-1 text-[11px] font-medium transition-colors ${
              idx > 0 ? "border-l border-slate-300" : ""
            } ${
              active
                ? "bg-blue-600 text-white shadow-inner"
                : "bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}

function NumberField({ label, value, onChange }: NumberFieldProps): JSX.Element {
  return (
    <label className="flex flex-col gap-0.5 text-[10px] font-medium uppercase tracking-wider text-slate-500">
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
        className="rounded border border-slate-300 bg-white px-2 py-1 font-mono text-[12px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
    </label>
  );
}

interface SwitchRowProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

function SwitchRow({ label, checked, onChange }: SwitchRowProps): JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded px-1 py-0.5 text-[12px] text-slate-700 hover:bg-slate-50"
    >
      <span>{label}</span>
      <span
        className={`relative inline-flex h-4 w-7 items-center rounded-full transition-colors ${checked ? "bg-blue-600" : "bg-slate-300"}`}
      >
        <span
          className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${checked ? "translate-x-3.5" : "translate-x-0.5"}`}
        />
      </span>
    </button>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFn = (key: any, defaultValue?: any) => string;

interface SignalRowProps {
  scopeId: string;
  signalIdx: number;
  signals: Record<string, SignalSettings> | undefined;
  totalSignals: number;
  markers: SignalMarker[];
  t: TFn;
}

function SignalRow({
  scopeId,
  signalIdx,
  signals,
  totalSignals,
  markers,
  t,
}: SignalRowProps): JSX.Element {
  const updateScopeSettings = useAppStore((s) => s.updateScopeSettings);
  const key = String(signalIdx);
  const sig = signals?.[key];
  const color = resolveSignalColor(signals, signalIdx);
  void totalSignals;

  const patch = (partial: SignalSettings): void => {
    updateScopeSettings(scopeId, {
      signals: {
        ...(signals ?? {}),
        [key]: { ...(sig ?? {}), ...partial },
      },
    });
  };

  return (
    <div className="flex items-center gap-2 px-2 py-1.5">
      <span className="w-10 font-mono text-[11px] text-slate-500">
        [{signalIdx}]
      </span>
      <ColorSwatch color={color} onChange={(c) => patch({ color: c })} />
      <select
        value={sig?.width ?? 1}
        onChange={(e) =>
          patch({ width: Number(e.target.value) as 1 | 2 | 3 })
        }
        className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        aria-label={t("scope.settings.signal.width", "Line width")}
      >
        <option value={1}>1 px</option>
        <option value={2}>2 px</option>
        <option value={3}>3 px</option>
      </select>
      <select
        value={sig?.marker ?? "none"}
        onChange={(e) => patch({ marker: e.target.value as SignalMarker })}
        className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-[11px] focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        aria-label={t("scope.settings.signal.marker", "Marker")}
      >
        {markers.map((m) => (
          <option key={m} value={m}>
            {t(`scope.settings.marker.${m}`, m)}
          </option>
        ))}
      </select>
    </div>
  );
}

interface ColorSwatchProps {
  color: string;
  onChange: (color: string) => void;
}

function ColorSwatch({ color, onChange }: ColorSwatchProps): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded border border-slate-300 bg-white py-0.5 pl-0.5 pr-1.5 hover:border-slate-400"
      >
        <span
          className="block h-4 w-6 rounded-sm border border-slate-200"
          style={{ backgroundColor: color }}
        />
        <span className="font-mono text-[10px] uppercase text-slate-600">
          {color.replace(/^#/, "")}
        </span>
      </button>
      {open && (
        <>
          {/* outside click で閉じる overlay */}
          <button
            type="button"
            aria-label="close color picker"
            className="fixed inset-0 z-10 cursor-default bg-transparent"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 top-7 z-20 rounded-md border border-slate-300 bg-white p-2 shadow-lg">
            <HexColorPicker color={color} onChange={onChange} />
            <input
              type="text"
              value={color}
              onChange={(e) => {
                const v = e.target.value.trim();
                if (/^#[0-9a-fA-F]{6}$/.test(v)) onChange(v);
              }}
              className="mt-2 w-full rounded border border-slate-300 px-1.5 py-0.5 font-mono text-[11px] uppercase focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline icons (lucide-style outline, 14px、Tailwind currentColor)
// ---------------------------------------------------------------------------

const _ICON_BASE = {
  width: 12,
  height: 12,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconAxisY(): JSX.Element {
  return (
    <svg {..._ICON_BASE}>
      <line x1="6" y1="3" x2="6" y2="21" />
      <line x1="6" y1="3" x2="3" y2="6" />
      <line x1="6" y1="3" x2="9" y2="6" />
      <line x1="10" y1="18" x2="20" y2="8" />
    </svg>
  );
}

function IconAxisX(): JSX.Element {
  return (
    <svg {..._ICON_BASE}>
      <line x1="3" y1="18" x2="21" y2="18" />
      <line x1="21" y1="18" x2="18" y2="15" />
      <line x1="21" y1="18" x2="18" y2="21" />
      <line x1="6" y1="6" x2="16" y2="16" />
    </svg>
  );
}

function IconLegend(): JSX.Element {
  return (
    <svg {..._ICON_BASE}>
      <line x1="4" y1="6" x2="6" y2="6" />
      <line x1="10" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="6" y2="12" />
      <line x1="10" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="6" y2="18" />
      <line x1="10" y1="18" x2="20" y2="18" />
    </svg>
  );
}

function IconGrid(): JSX.Element {
  return (
    <svg {..._ICON_BASE}>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function IconSignal(): JSX.Element {
  return (
    <svg {..._ICON_BASE}>
      <polyline points="3 17 9 11 13 15 21 7" />
    </svg>
  );
}

function IconWarning(): JSX.Element {
  return (
    <svg {..._ICON_BASE} className="mt-0.5 shrink-0">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}
