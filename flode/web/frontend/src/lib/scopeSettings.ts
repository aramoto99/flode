// ADR-0044 §論点 4 / §論点 9: Scope プロット設定の defaults と merge ロジック。

import type { ScopeBuffer } from "../store/appStore";
import type { ScopeSettings, SignalSettings } from "../types/api";

/**
 * flode hard-coded default。モデル保存値が無いときに使用する。
 * background は常に white (= ダークモード out-of-scope)。
 */
export const DEFAULT_SCOPE_SETTINGS: Required<
  Omit<ScopeSettings, "y_min" | "y_max" | "x_min" | "x_max" | "signals">
> &
  Pick<ScopeSettings, "y_min" | "y_max" | "x_min" | "x_max" | "signals"> = {
  y_mode: "auto",
  x_mode: "auto",
  legend: "top",
  grid_major: true,
  grid_minor: false,
  signals: undefined,
  y_min: undefined,
  y_max: undefined,
  x_min: undefined,
  x_max: undefined,
};

/**
 * uPlot 自動色 8 色 (= ADR-0023 §Decision §(7) を ADR-0044 で fallback 化)。
 * per-signal 設定で color 未指定時にこの配列から signal_idx % 8 で割り当てる。
 */
export const FALLBACK_COLORS = [
  "#3b82f6", // blue-500
  "#ef4444", // red-500
  "#10b981", // emerald-500
  "#f59e0b", // amber-500
  "#8b5cf6", // violet-500
  "#ec4899", // pink-500
  "#14b8a6", // teal-500
  "#f97316", // orange-500
] as const;

/**
 * 保存値と default を merge する (= 保存値優先、欠落分は default で埋める)。
 */
export function resolveSettings(saved: ScopeSettings | undefined): ScopeSettings {
  if (!saved) {
    return { ...DEFAULT_SCOPE_SETTINGS };
  }
  return {
    y_mode: saved.y_mode ?? DEFAULT_SCOPE_SETTINGS.y_mode,
    y_min: saved.y_min,
    y_max: saved.y_max,
    x_mode: saved.x_mode ?? DEFAULT_SCOPE_SETTINGS.x_mode,
    x_min: saved.x_min,
    x_max: saved.x_max,
    legend: saved.legend ?? DEFAULT_SCOPE_SETTINGS.legend,
    grid_major: saved.grid_major ?? DEFAULT_SCOPE_SETTINGS.grid_major,
    grid_minor: saved.grid_minor ?? DEFAULT_SCOPE_SETTINGS.grid_minor,
    signals: saved.signals,
  };
}

/**
 * signal_idx に対する line color を返す (= 保存値 → 8 色 fallback)。
 */
export function resolveSignalColor(
  signalSettings: Record<string, SignalSettings> | undefined,
  signalIdx: number,
): string {
  const explicit = signalSettings?.[String(signalIdx)]?.color;
  if (explicit) return explicit;
  return FALLBACK_COLORS[signalIdx % FALLBACK_COLORS.length]!;
}

/**
 * Y 軸 log 化が安全か検証 (= 全値が正数なら true、0 / 負値があれば false)。
 * 安全でない場合は呼び出し側で auto に fallback + warning を出す想定。
 */
export function canUseLogScale(buffer: ScopeBuffer | undefined): boolean {
  if (!buffer) return true;
  for (const col of buffer.values) {
    for (let i = 0; i < buffer.length; i++) {
      const v = col[i];
      if (v === undefined || v <= 0 || !Number.isFinite(v)) return false;
    }
  }
  return true;
}
