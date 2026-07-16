// ADR-0044 §論点 4 / §論点 7 / §論点 9: per-Scope プロット設定 dialog。
// v0.25.0: ui/inspector.tsx primitives ベースに refactor (= ModelSettings /
// ParameterPanel と統一)。設計詳細は ``components/ui/inspector.tsx`` 参照。

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
import {
  DialogFooter,
  DialogShell,
  INPUT_MONO_CLS,
  NumberInput,
  PrimaryButton,
  PropertyGrid,
  PropertyRow,
  SecondaryButton,
  SELECT_CLS,
  SectionDivider,
  TabBar,
  TabButton,
} from "./ui/inspector";

interface ScopeSettingsDialogProps {
  scopeId: string;
  onClose: () => void;
  /** XYGraph 用ダイアログか。true のとき log/凡例/minor grid/複数 signal を隠し、
   *  トレース 1 本分の style のみ出す (= XY に効く項目だけ表示)。 */
  isXY?: boolean;
}

type TabKey = "display" | "style";

export function ScopeSettingsDialog({
  scopeId,
  onClose,
  isXY = false,
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

  return (
    <DialogShell
      title={`${t("scope.settings.title_v2", "Scope Properties")}: ${scopeId}`}
      width="w-[540px]"
      onClose={onClose}
      footer={
        <DialogFooter
          left={
            <SecondaryButton onClick={() => resetScopeSettings(scopeId)}>
              {t("scope.settings.reset", "Reset to defaults")}
            </SecondaryButton>
          }
          right={<PrimaryButton onClick={onClose}>OK</PrimaryButton>}
        />
      }
    >
      <TabBar>
        <TabButton active={tab === "display"} onClick={() => setTab("display")}>
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
      </TabBar>

      <div className="h-[340px] overflow-y-auto bg-white px-3 py-2.5">
        {tab === "display" && (
          <DisplayTab
            settings={settings}
            logSafe={logSafe}
            isXY={isXY}
            onPatch={(p) => updateScopeSettings(scopeId, p)}
          />
        )}
        {tab === "style" && (
          <StyleTab
            signals={settings.signals}
            // XYGraph は単一トレース (= buffer の x,y 2 列でも style は 1 本)。
            // データ未取得でも色を設定できるよう常に 1 行表示する。
            nSignals={isXY ? 1 : nSignals}
            isXY={isXY}
            onPatch={(p) => updateScopeSettings(scopeId, p)}
          />
        )}
      </div>
    </DialogShell>
  );
}

// ---------------------------------------------------------------------------
// Display tab
// ---------------------------------------------------------------------------

type ResolvedSettings = ReturnType<typeof resolveSettings>;

function DisplayTab({
  settings,
  logSafe,
  isXY,
  onPatch,
}: {
  settings: ResolvedSettings;
  logSafe: boolean;
  isXY: boolean;
  onPatch: (p: Partial<ResolvedSettings>) => void;
}): JSX.Element {
  const { t } = useTranslation();
  return (
    <PropertyGrid>
      <SectionDivider label={t("scope.settings.section.y", "Y axis")} />
      <PropertyRow label={t("scope.settings.y_mode_label", "Scale")}>
        <select
          value={settings.y_mode}
          onChange={(e) =>
            onPatch({ y_mode: e.target.value as "auto" | "manual" | "log" })
          }
          className={`${SELECT_CLS} w-28`}
        >
          <option value="auto">{t("scope.settings.y_mode.auto", "Auto")}</option>
          <option value="manual">
            {t("scope.settings.y_mode.manual", "Manual")}
          </option>
          {/* XYGraph は log 軸非対応 (= パラメトリック軌跡) のため log を出さない。 */}
          {!isXY && (
            <option value="log">{t("scope.settings.y_mode.log", "Log")}</option>
          )}
        </select>
        {!isXY && settings.y_mode === "log" && !logSafe && (
          <span className="ml-2 text-[10px] text-amber-700">
            ⚠{" "}
            {t(
              "scope.warnings.log_fallback_short",
              "non-positive → auto",
            )}
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
          className={`${SELECT_CLS} w-28`}
        >
          <option value="auto">{t("scope.settings.x_mode.auto", "Auto")}</option>
          <option value="manual">
            {t("scope.settings.x_mode.manual", "Manual")}
          </option>
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
      {/* XYGraph は単一トレースで凡例を持たないため凡例行は出さない。 */}
      {!isXY && (
        <PropertyRow label={t("scope.settings.section.legend", "Legend")}>
          <select
            value={settings.legend}
            onChange={(e) =>
              onPatch({
                legend: e.target.value as "top" | "bottom" | "right" | "off",
              })
            }
            className={`${SELECT_CLS} w-28`}
          >
            <option value="top">{t("scope.settings.legend.top", "Top")}</option>
            <option value="bottom">
              {t("scope.settings.legend.bottom", "Bottom")}
            </option>
            <option value="right">
              {t("scope.settings.legend.right", "Right")}
            </option>
            <option value="off">{t("scope.settings.legend.off", "Off")}</option>
          </select>
        </PropertyRow>
      )}
      <PropertyRow label={t("scope.settings.grid.major", "Major grid")}>
        <input
          type="checkbox"
          checked={settings.grid_major !== false}
          onChange={(e) => onPatch({ grid_major: e.target.checked })}
          className="cursor-pointer"
        />
      </PropertyRow>
      {/* XYGraph は minor grid 非対応 (= 枠 + major grid のみ)。 */}
      {!isXY && (
        <PropertyRow label={t("scope.settings.grid.minor", "Minor grid")}>
          <input
            type="checkbox"
            checked={settings.grid_minor === true}
            onChange={(e) => onPatch({ grid_minor: e.target.checked })}
            className="cursor-pointer"
          />
        </PropertyRow>
      )}
    </PropertyGrid>
  );
}

// ---------------------------------------------------------------------------
// Style tab
// ---------------------------------------------------------------------------

function StyleTab({
  signals,
  nSignals,
  isXY,
  onPatch,
}: {
  signals: Record<string, SignalSettings> | undefined;
  nSignals: number;
  isXY: boolean;
  onPatch: (p: { signals: Record<string, SignalSettings> }) => void;
}): JSX.Element {
  const { t } = useTranslation();
  if (nSignals === 0) {
    return (
      <div className="py-6 text-center text-[11px] text-slate-500">
        {t(
          "scope.settings.no_signals",
          "No signals yet (run the simulation).",
        )}
      </div>
    );
  }
  const markers: SignalMarker[] = ["none", "circle", "square", "cross"];
  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-[36px_1fr_70px_90px] gap-2 border-b border-slate-300 bg-slate-100 px-1 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-600">
        <span>
          {isXY
            ? t("scope.settings.trace.col", "Trace")
            : t("scope.settings.signals.col.idx", "#")}
        </span>
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
              className={`${SELECT_CLS} w-full`}
              aria-label={t("scope.settings.signal.width", "Line width")}
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
              className={`${SELECT_CLS} w-full`}
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
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ColorSwatch (local — react-colorful 統合)
// ---------------------------------------------------------------------------

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
              className={`${INPUT_MONO_CLS} mt-2 w-full uppercase`}
            />
          </div>
        </>
      )}
    </div>
  );
}
