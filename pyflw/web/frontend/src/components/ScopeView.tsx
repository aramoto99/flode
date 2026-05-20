// ADR-0023: Scope ストリームの可視化を uPlot 化。
// ADR-0044: per-scope プロット設定 + ヘッダー (= 設定 / 最大化 / panel 化ボタン)。
//
// データフロー:
//   appStore.scopes[scopeId]: ScopeBuffer (SoA, Float64Array)
//     -> ``buildAlignedData(buffer)``: uPlot.AlignedData の subarray view を生成
//     -> UPlotChart に渡す
//
// uPlot options は ``buffer.n_signals`` + ``scopeId`` + settings ごとに生成して
// useMemo で参照固定 (= UPlotChart の effect が再生成 trigger するのを抑える)。

import uPlot from "uplot";
import { useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { deriveLegend, exportScopeImage } from "../lib/scopeImageExport";
import {
  DEFAULT_SCOPE_SETTINGS,
  FALLBACK_COLORS,
  canUseLogScale,
  resolveSettings,
  resolveSignalColor,
} from "../lib/scopeSettings";
import { type ScopeBuffer, useAppStore } from "../store/appStore";
import { pushToast } from "../store/toastStore";
import type { ScopeSettings } from "../types/api";
import { UPlotChart } from "./UPlotChart";

interface ScopeViewProps {
  scopeId: string;
  buffer: ScopeBuffer;
  /** ADR-0044 §論点 10: ``"inline"`` (Canvas 下部) / ``"panel"`` (floating window) */
  formFactor?: "inline" | "panel";
  /** ヘッダーを完全に非表示 (= 旧テスト互換用)。 */
  hideHeader?: boolean;
}

/** ScopeBuffer から uPlot AlignedData (= ゼロコピー subarray view) を組み立てる。
 * @internal テスト用 export。
 */
export function buildAlignedData(buffer: ScopeBuffer): uPlot.AlignedData {
  if (buffer.length === 0 || buffer.n_signals === 0) {
    return [new Float64Array(0), new Float64Array(0)];
  }
  const xs = buffer.times.subarray(0, buffer.length);
  const ys = buffer.values.map((col) => col.subarray(0, buffer.length));
  return [xs, ...ys] as uPlot.AlignedData;
}

/** uPlot.Options を組み立てる。
 *
 * ADR-0044 §論点 4 / §論点 7: per-scope settings から
 * - Y/X 軸スケール (auto / manual / log)
 * - 凡例位置 (= legend.show + 配置は React 側で wrapper、本関数は show のみ)
 * - グリッド (major / minor)
 * - per-signal 線色 / 線幅
 *
 * @internal テスト用 export。
 */
export function buildOptions(
  scopeId: string,
  n_signals: number,
  settings: ScopeSettings,
  buffer?: ScopeBuffer,
): uPlot.Options {
  const resolved = resolveSettings(settings);
  // ADR-0044 §論点 7: log で 0/負値があれば auto に fallback
  const yMode =
    resolved.y_mode === "log" && buffer && !canUseLogScale(buffer)
      ? "auto"
      : resolved.y_mode!;

  const series: uPlot.Series[] = [
    {}, // x 軸 (時間)
    ...Array.from({ length: n_signals }, (_, i): uPlot.Series => ({
      label: n_signals === 1 ? scopeId : `${scopeId}[${i}]`,
      stroke: resolveSignalColor(resolved.signals, i),
      width: resolved.signals?.[String(i)]?.width ?? 1.25,
      points: { show: false },
    })),
  ];

  const xRange =
    resolved.x_mode === "manual" &&
    typeof resolved.x_min === "number" &&
    typeof resolved.x_max === "number"
      ? { min: resolved.x_min, max: resolved.x_max }
      : undefined;
  const yRange =
    yMode === "manual" &&
    typeof resolved.y_min === "number" &&
    typeof resolved.y_max === "number"
      ? { min: resolved.y_min, max: resolved.y_max }
      : undefined;

  // v0.32.2: フォント / 軸色 / グリッドの styling を UI design system に統一
  // (= 旧デフォルトは tick label が大きく "t [s]" が中央大型表示で「web 標準
  // っぽい」見た目になっていた)。Property Inspector 風の 11 px sans-
  // serif + slate-500 系で密度を上げ、X 軸 label は左寄せ小さく。
  const AXIS_FONT = '11px system-ui, "Segoe UI", -apple-system, sans-serif';
  const AXIS_LABEL_FONT =
    '10px system-ui, "Segoe UI", -apple-system, sans-serif';
  const AXIS_STROKE = "#64748b"; // slate-500 (旧 slate-400 は薄すぎた)
  const GRID_STROKE = "#e2e8f0"; // slate-200
  const TICK_STROKE = "#cbd5e1"; // slate-300

  return {
    width: 400,
    height: 192,
    series,
    scales: {
      x: {
        time: false,
        ...(xRange ? { auto: false, range: () => [xRange.min, xRange.max] } : {}),
      },
      y: {
        ...(yMode === "log" ? { distr: 3 as const } : {}),
        ...(yRange ? { auto: false, range: () => [yRange.min, yRange.max] } : {}),
      },
    },
    axes: [
      {
        stroke: AXIS_STROKE,
        font: AXIS_FONT,
        labelFont: AXIS_LABEL_FONT,
        size: 28,
        gap: 3,
        labelGap: 0,
        labelSize: 14,
        grid: {
          stroke: GRID_STROKE,
          width: 1,
          show: resolved.grid_major !== false,
        },
        ticks: { stroke: TICK_STROKE, width: 1, size: 4 },
        label: "t [s]",
      },
      {
        stroke: AXIS_STROKE,
        font: AXIS_FONT,
        labelFont: AXIS_LABEL_FONT,
        size: 38,
        gap: 3,
        grid: {
          stroke: GRID_STROKE,
          width: 1,
          show: resolved.grid_major !== false,
        },
        ticks: { stroke: TICK_STROKE, width: 1, size: 4 },
      },
    ],
    legend: {
      show: resolved.legend !== "off",
      live: false,
    },
    cursor: { show: true, drag: { x: true, y: false } },
  };
}

/**
 * Scope ストリームを uPlot で時系列描画するコンポーネント。
 */
export function ScopeView({
  scopeId,
  buffer,
  formFactor = "inline",
  hideHeader = false,
}: ScopeViewProps): JSX.Element {
  const { t } = useTranslation();
  const editingModel = useAppStore((s) => s.editingModel);
  const setEditingScopeSettingsId = useAppStore(
    (s) => s.setEditingScopeSettingsId,
  );
  const openScopePanel = useAppStore((s) => s.openScopePanel);
  const closeScopePanel = useAppStore((s) => s.closeScopePanel);
  // plot 領域 (= uPlot canvas の親) を画像コピー時に querySelector する用。
  const plotAreaRef = useRef<HTMLDivElement | null>(null);

  const settings = editingModel?.scope_settings?.[scopeId] ?? DEFAULT_SCOPE_SETTINGS;

  // グラフ画像をクリップボードへコピー (失敗時 download)。凡例も合成する。
  const handleCopyImage = async (): Promise<void> => {
    const canvas = plotAreaRef.current?.querySelector("canvas");
    if (!(canvas instanceof HTMLCanvasElement)) return;
    const resolved = resolveSettings(settings);
    const legend = deriveLegend(scopeId, buffer.n_signals, resolved.signals);
    try {
      const result = await exportScopeImage(canvas, legend, `${scopeId}.png`);
      pushToast({
        severity: "info",
        message: t(
          result === "copied"
            ? "scope.copy_image.copied"
            : "scope.copy_image.downloaded",
        ),
      });
    } catch {
      pushToast({ severity: "error", message: t("scope.copy_image.error") });
    }
  };

  // ADR-0044 §論点 4: options は buffer 変更ごとに再計算しない
  // (= 毎 WS scope_batch で uPlot を destroy/recreate してしまうのを避ける)。
  // 再生成 trigger は ``scopeId`` / ``n_signals`` / ``settings`` 変更のみ。
  // log fallback は buffer の参照を使うが、recheck タイミングは settings 変更時
  // のみで OK (= log mode に切替えた時点で再評価され、その後はモード一定)。
  const options = useMemo(
    () =>
      buildOptions(scopeId, Math.max(buffer.n_signals, 1), settings, buffer),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scopeId, buffer.n_signals, settings],
  );
  const data = useMemo(
    () => buildAlignedData(buffer),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- length 変化で再計算
    [buffer, buffer.length],
  );

  // ADR-0044 §論点 4 / §論点 6 / §論点 8: ヘッダー (= 設定 / 最大化 / panel 化)。
  // panel mode 時は ``scope-panel-drag-handle`` クラスを付与し、Rnd の drag 起点にする。
  const header = !hideHeader && (
    <div
      className={`flex h-6 shrink-0 items-center gap-1 border-b border-slate-200 bg-slate-50 px-2 text-[11px] text-slate-700 ${
        formFactor === "panel" ? "scope-panel-drag-handle cursor-move" : ""
      }`}
    >
      {/* inline (= タブ表示) 時は scope_id がタブ側に出るため重複ラベルを省く。
          floating panel 時はウィンドウ識別に必要なので表示する。 */}
      {formFactor === "panel" && (
        <span className="font-mono font-medium">{scopeId}</span>
      )}
      <div className="flex-1" />
      {/* グラフ画像をクリップボードへコピー (= データがある時のみ)。 */}
      {buffer.length > 0 && (
        <button
          type="button"
          title={t("scope.button.copy_image", "Copy image")}
          onClick={() => void handleCopyImage()}
          className="flex h-4 w-4 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
        >
          <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="M21 15l-5-5L5 21" />
          </svg>
        </button>
      )}
      <button
        type="button"
        title={t("scope.button.settings", "Settings")}
        onClick={() => setEditingScopeSettingsId(scopeId)}
        className="flex h-4 w-4 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
      >
        <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
      {formFactor === "inline" && (
        <>
          <button
            type="button"
            title={t("scope.button.open_panel", "Open in floating panel")}
            onClick={() => openScopePanel(scopeId)}
            className="flex h-4 w-4 items-center justify-center rounded text-slate-500 hover:bg-slate-200 hover:text-slate-800"
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 3h7v7M10 21H3v-7M21 3l-9 9M3 21l9-9" />
            </svg>
          </button>
        </>
      )}
      {formFactor === "panel" && (
        <button
          type="button"
          title={t("scope.button.close_panel", "Close panel")}
          onClick={() => closeScopePanel(scopeId)}
          className="flex h-4 w-4 items-center justify-center rounded text-slate-500 hover:bg-rose-100 hover:text-rose-600"
        >
          <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.5">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );

  if (buffer.length === 0) {
    return (
      <div className="flex h-full w-full flex-col border border-slate-200 bg-white">
        {header}
        <div className="flex flex-1 items-center justify-center text-[12px] text-slate-400">
          {t("scopeview.no_data", { scope_id: scopeId })}
        </div>
      </div>
    );
  }

  return (
    // 旧 inline は h-48 固定 (= Canvas 下部に縦積みしていた名残) だったが、
    // タブ表示で 1 個ずつ見せる現行レイアウトでは親ペインを満たすべきなので
    // h-full に統一する。実寸への uPlot 追従は UPlotChart の ResizeObserver が担う。
    <div className="flex h-full w-full flex-col border border-slate-200 bg-white">
      {header}
      <div ref={plotAreaRef} className="relative flex-1">
        <UPlotChart options={options} data={data} className="absolute inset-0" />
      </div>
    </div>
  );
}

// FALLBACK_COLORS / SCOPE_COLORS の export 互換性 (旧テスト): re-export
export { FALLBACK_COLORS as SCOPE_COLORS };
