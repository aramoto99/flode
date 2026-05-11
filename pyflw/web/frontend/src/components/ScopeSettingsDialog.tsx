// ADR-0044 §論点 4 / §論点 7 / §論点 9: per-Scope プロット設定 dialog。
//
// v0.24.4: Simulink Property Inspector を参考に「タブ + プロパティグリッド +
// ネイティブ widget」スタイルへ刷新 (= 旧版 v0.24.3 を「安っぽい」と再指摘されたため)。
// - 上部に Display / Style の 2 タブ
// - 各タブは「ラベル (右寄せ) | 入力 (左寄せ)」の 2 列プロパティグリッド
// - native ``<select>`` / ``<input>`` / ``<input type="checkbox">`` 使用
// - rounded を最小化、border は 1px 直線で機能的なウィンドウ感
// - title bar / footer に subtle gradient
//
// 永続化先は ``editingModel.scope_settings[scopeId]`` (= モデル単位、ADR-0044 §論点 1)。

import { useEffect, useState } from "react";
import { HexColorPicker } from "react-colorful";
import { useTranslation } from "react-i18next";

import {
  canUseLogScale,
  resolveSettings,
  resolveSignalColor,
} from "../lib/scopeSettings";
import { useAppStore } from "../store/appStore";
import type { SignalMarker, SignalSettings } from "../types/api";

interface ScopeSettingsDialogProps {
  scopeId: string;
  onClose: () => void;
}

type TabKey = "display" | "style";

export function ScopeSettingsDialog({
  scopeId,
  onClose,
}: ScopeSettingsDialogProps): JSX.Element {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);
  const updateScopeSettings = useAppStore((s) => s.updateScopeSettings);
  const resetScopeSettings = useAppStore((s) => s.resetScopeSettings);
  const buffer = useAppStore((s) => s.scopes[scopeId]);
  const [tab, setTab] = useState<TabKey>("display");

  const saved = editingModel?.scope_settings?.[scopeId];
  const settings = resolveSettings(saved);
  const nSignals = buffer?.n_signals ?? 0;
  const logSafe = canUseLogScale(buffer);

  // ESC で閉じる
  useEffect(() => {
    const h = (e: KeyboardEvent): void => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30"
      onClick={onClose}
    >
      <div
        className="w-[540px] border border-slate-400 bg-slate-50 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Scope Properties: ${scopeId}`}
      >
        {/* Title bar (Simulink 風 native dialog header) */}
        <div className="flex items-center justify-between border-b border-slate-400 bg-gradient-to-b from-slate-200 to-slate-100 px-3 py-1">
          <span className="text-[12px] font-semibold text-slate-800">
            {t("scope.settings.title_v2", "Scope Properties")}: {scopeId}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-5 w-5 items-center justify-center text-slate-600 hover:bg-slate-300 hover:text-slate-900"
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex items-end gap-0 border-b border-slate-400 bg-slate-100 pl-2 pt-1">
          <TabButton
            active={tab === "display"}
            onClick={() => setTab("display")}
          >
            {t("scope.settings.tab.display", "Display")}
          </TabButton>
          <TabButton active={tab === "style"} onClick={() => setTab("style")}>
            {t("scope.settings.tab.style", "Style")}
            {nSignals > 0 && (
              <span className="ml-1 text-[10px] text-slate-500">
                ({nSignals})
              </span>
            )}
          </TabButton>
        </div>

        {/* Content (固定高さ — タブ切替で window 寸法が変動しないように) */}
        <div className="h-[340px] overflow-y-auto bg-white px-3 py-2.5">
          {tab === "display" && (
            <DisplayTab
              t={t}
              settings={settings}
              logSafe={logSafe}
              onPatch={(p) => updateScopeSettings(scopeId, p)}
            />
          )}
          {tab === "style" && (
            <StyleTab
              t={t}
              scopeId={scopeId}
              signals={settings.signals}
              nSignals={nSignals}
              onPatch={(p) => updateScopeSettings(scopeId, p)}
            />
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-400 bg-gradient-to-b from-slate-100 to-slate-200 px-3 py-1.5">
          <button
            type="button"
            onClick={() => resetScopeSettings(scopeId)}
            className="border border-slate-400 bg-white px-2.5 py-0.5 text-[11px] text-slate-700 hover:bg-slate-50 active:bg-slate-200"
          >
            {t("scope.settings.reset", "Reset to defaults")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="border border-slate-500 bg-blue-600 px-4 py-0.5 text-[11px] font-medium text-white hover:bg-blue-700 active:bg-blue-800"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab buttons
// ---------------------------------------------------------------------------

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`-mb-px border border-b-0 px-3 py-0.5 text-[11px] ${
        active
          ? "border-slate-400 bg-white text-slate-800 font-medium"
          : "border-transparent bg-slate-100 text-slate-600 hover:text-slate-800"
      }`}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Property grid primitives (Simulink Property Inspector スタイル)
// ---------------------------------------------------------------------------

function PropertyRow({
  label,
  children,
  indent = false,
}: {
  label: string;
  children: React.ReactNode;
  indent?: boolean;
}): JSX.Element {
  return (
    <div className="flex min-h-[22px] items-center gap-2 py-0.5">
      <label
        className={`w-[140px] shrink-0 text-right text-[11px] text-slate-700 ${
          indent ? "pl-3" : ""
        }`}
      >
        {label}:
      </label>
      <div className="flex flex-1 items-center">{children}</div>
    </div>
  );
}

function SectionDivider({ label }: { label: string }): JSX.Element {
  return (
    <div className="my-1.5 flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-200" />
    </div>
  );
}

const NATIVE_INPUT_CLS =
  "border border-slate-400 bg-white px-1.5 py-0 text-[11px] text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const NATIVE_SELECT_CLS =
  "border border-slate-400 bg-white px-1 py-0 text-[11px] text-slate-800 focus:border-blue-500 focus:outline-none";

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TFn = (key: any, defaultValue?: any) => string;

type ResolvedSettings = ReturnType<typeof resolveSettings>;

interface DisplayTabProps {
  t: TFn;
  settings: ResolvedSettings;
  logSafe: boolean;
  onPatch: (p: Partial<ResolvedSettings>) => void;
}

function DisplayTab({
  t,
  settings,
  logSafe,
  onPatch,
}: DisplayTabProps): JSX.Element {
  return (
    <div className="flex flex-col">
      <SectionDivider label={t("scope.settings.section.y", "Y axis")} />
      <PropertyRow label={t("scope.settings.y_mode_label", "Scale")}>
        <select
          value={settings.y_mode}
          onChange={(e) =>
            onPatch({ y_mode: e.target.value as "auto" | "manual" | "log" })
          }
          className={`${NATIVE_SELECT_CLS} w-28`}
        >
          <option value="auto">{t("scope.settings.y_mode.auto", "Auto")}</option>
          <option value="manual">{t("scope.settings.y_mode.manual", "Manual")}</option>
          <option value="log">{t("scope.settings.y_mode.log", "Log")}</option>
        </select>
        {settings.y_mode === "log" && !logSafe && (
          <span className="ml-2 text-[10px] text-amber-700">
            ⚠ {t("scope.warnings.log_fallback_short", "non-positive → auto")}
          </span>
        )}
      </PropertyRow>
      {settings.y_mode === "manual" && (
        <>
          <PropertyRow indent label={t("scope.settings.y_min", "Y min")}>
            <NumberInput
              value={settings.y_min}
              onChange={(v) => onPatch({ y_min: v })}
            />
          </PropertyRow>
          <PropertyRow indent label={t("scope.settings.y_max", "Y max")}>
            <NumberInput
              value={settings.y_max}
              onChange={(v) => onPatch({ y_max: v })}
            />
          </PropertyRow>
        </>
      )}

      <SectionDivider label={t("scope.settings.section.x", "X axis")} />
      <PropertyRow label={t("scope.settings.x_mode_label", "Scale")}>
        <select
          value={settings.x_mode}
          onChange={(e) =>
            onPatch({ x_mode: e.target.value as "auto" | "manual" })
          }
          className={`${NATIVE_SELECT_CLS} w-28`}
        >
          <option value="auto">{t("scope.settings.x_mode.auto", "Auto")}</option>
          <option value="manual">{t("scope.settings.x_mode.manual", "Manual")}</option>
        </select>
      </PropertyRow>
      {settings.x_mode === "manual" && (
        <>
          <PropertyRow indent label={t("scope.settings.x_min", "X min")}>
            <NumberInput
              value={settings.x_min}
              onChange={(v) => onPatch({ x_min: v })}
            />
          </PropertyRow>
          <PropertyRow indent label={t("scope.settings.x_max", "X max")}>
            <NumberInput
              value={settings.x_max}
              onChange={(v) => onPatch({ x_max: v })}
            />
          </PropertyRow>
        </>
      )}

      <SectionDivider
        label={t("scope.settings.section.layout", "Layout")}
      />
      <PropertyRow label={t("scope.settings.section.legend", "Legend")}>
        <select
          value={settings.legend}
          onChange={(e) =>
            onPatch({
              legend: e.target.value as "top" | "bottom" | "right" | "off",
            })
          }
          className={`${NATIVE_SELECT_CLS} w-28`}
        >
          <option value="top">{t("scope.settings.legend.top", "Top")}</option>
          <option value="bottom">{t("scope.settings.legend.bottom", "Bottom")}</option>
          <option value="right">{t("scope.settings.legend.right", "Right")}</option>
          <option value="off">{t("scope.settings.legend.off", "Off")}</option>
        </select>
      </PropertyRow>
      <PropertyRow label={t("scope.settings.grid.major", "Major grid")}>
        <input
          type="checkbox"
          checked={settings.grid_major !== false}
          onChange={(e) => onPatch({ grid_major: e.target.checked })}
          className="cursor-pointer"
        />
      </PropertyRow>
      <PropertyRow label={t("scope.settings.grid.minor", "Minor grid")}>
        <input
          type="checkbox"
          checked={settings.grid_minor === true}
          onChange={(e) => onPatch({ grid_minor: e.target.checked })}
          className="cursor-pointer"
        />
      </PropertyRow>
    </div>
  );
}

interface StyleTabProps {
  t: TFn;
  scopeId: string;
  signals: Record<string, SignalSettings> | undefined;
  nSignals: number;
  onPatch: (p: { signals: Record<string, SignalSettings> }) => void;
}

function StyleTab({
  t,
  signals,
  nSignals,
  onPatch,
}: StyleTabProps): JSX.Element {
  if (nSignals === 0) {
    return (
      <div className="py-6 text-center text-[11px] text-slate-500">
        {t("scope.settings.no_signals", "No signals yet (run the simulation).")}
      </div>
    );
  }
  const markers: SignalMarker[] = ["none", "circle", "square", "cross"];
  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="grid grid-cols-[36px_1fr_70px_90px] gap-2 border-b border-slate-300 bg-slate-100 px-1 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
        <span>{t("scope.settings.signals.col.idx", "#")}</span>
        <span>{t("scope.settings.signals.col.color", "Color")}</span>
        <span>{t("scope.settings.signals.col.width", "Width")}</span>
        <span>{t("scope.settings.signals.col.marker", "Marker")}</span>
      </div>
      {Array.from({ length: nSignals }, (_, i) => {
        const key = String(i);
        const sig = signals?.[key];
        const color = resolveSignalColor(signals, i);
        const patch = (partial: SignalSettings): void => {
          onPatch({
            signals: {
              ...(signals ?? {}),
              [key]: { ...(sig ?? {}), ...partial },
            },
          });
        };
        return (
          <div
            key={i}
            className="grid grid-cols-[36px_1fr_70px_90px] items-center gap-2 border-b border-slate-100 px-1 py-1 hover:bg-slate-50"
          >
            <span className="font-mono text-[11px] text-slate-600">[{i}]</span>
            <ColorSwatch color={color} onChange={(c) => patch({ color: c })} />
            <select
              value={sig?.width ?? 1}
              onChange={(e) =>
                patch({ width: Number(e.target.value) as 1 | 2 | 3 })
              }
              className={`${NATIVE_SELECT_CLS} w-full`}
            >
              <option value={1}>1 px</option>
              <option value={2}>2 px</option>
              <option value={3}>3 px</option>
            </select>
            <select
              value={sig?.marker ?? "none"}
              onChange={(e) =>
                patch({ marker: e.target.value as SignalMarker })
              }
              className={`${NATIVE_SELECT_CLS} w-full`}
            >
              {markers.map((m) => (
                <option key={m} value={m}>
                  {t(`scope.settings.marker.${m}`, m)}
                </option>
              ))}
            </select>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small components
// ---------------------------------------------------------------------------

function NumberInput({
  value,
  onChange,
}: {
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}): JSX.Element {
  return (
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
      className={`${NATIVE_INPUT_CLS} w-24 font-mono`}
    />
  );
}

function ColorSwatch({
  color,
  onChange,
}: {
  color: string;
  onChange: (c: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Pick color"
        className="h-4 w-8 border border-slate-400 hover:border-slate-600"
        style={{ backgroundColor: color }}
      />
      <span className="font-mono text-[10px] uppercase text-slate-600">
        {color.replace(/^#/, "")}
      </span>
      {open && (
        <>
          <button
            type="button"
            aria-label="close color picker"
            className="fixed inset-0 z-10 cursor-default bg-transparent"
            onClick={() => setOpen(false)}
          />
          <div className="absolute left-0 top-6 z-20 border border-slate-400 bg-white p-2 shadow-lg">
            <HexColorPicker color={color} onChange={onChange} />
            <input
              type="text"
              value={color}
              onChange={(e) => {
                const v = e.target.value.trim();
                if (/^#[0-9a-fA-F]{6}$/.test(v)) onChange(v);
              }}
              className={`${NATIVE_INPUT_CLS} mt-2 w-full font-mono uppercase`}
            />
          </div>
        </>
      )}
    </div>
  );
}
