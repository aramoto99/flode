// ADR-0023: Scope ストリームの可視化を uPlot 化。
// 旧 canvas 自前実装 (ADR-0012 §(7) で「Phase 3 で uPlot に置換」と宣言) を完全置換し、
// 100k 点規模で 60fps スクロールを担保する。
//
// データフロー:
//   appStore.scopes[scopeId]: ScopeBuffer (SoA, Float64Array)
//     -> ``buildAlignedData(buffer)``: uPlot.AlignedData の subarray view を生成
//        (= ゼロコピー、length に応じて先頭から view を切る)
//     -> UPlotChart に渡す
//
// uPlot options は ``buffer.n_signals`` + ``scopeId`` ごとに 1 回だけ生成し
// useMemo で参照固定 (= UPlotChart の effect が再生成 trigger するのを抑える)。

import uPlot from "uplot";
import { useMemo } from "react";

import type { ScopeBuffer } from "../store/appStore";
import { UPlotChart } from "./UPlotChart";

interface ScopeViewProps {
  scopeId: string;
  buffer: ScopeBuffer;
}

/** Tailwind パレット 8 色ローテーション (ADR-0023 §Decision §(7))。 */
const SCOPE_COLORS = [
  "#0ea5e9", // sky-500
  "#10b981", // emerald-500
  "#f59e0b", // amber-500
  "#f43f5e", // rose-500
  "#8b5cf6", // violet-500
  "#06b6d4", // cyan-500
  "#84cc16", // lime-500
  "#ec4899", // pink-500
];

/** ScopeBuffer から uPlot AlignedData (= ゼロコピー subarray view) を組み立てる。
 * @internal テスト用 export。
 */
export function buildAlignedData(buffer: ScopeBuffer): uPlot.AlignedData {
  if (buffer.length === 0 || buffer.n_signals === 0) {
    // 空データ: uPlot は最低限 [xs, ys1] を要求するので 1 系列の空 array を返す
    return [new Float64Array(0), new Float64Array(0)];
  }
  const xs = buffer.times.subarray(0, buffer.length);
  const ys = buffer.values.map((col) => col.subarray(0, buffer.length));
  return [xs, ...ys] as uPlot.AlignedData;
}

/** uPlot.Options を信号数 / scopeId / サイズから組み立てる。
 * @internal テスト用 export。
 */
export function buildOptions(scopeId: string, n_signals: number): uPlot.Options {
  const series: uPlot.Series[] = [
    {}, // x 軸 (時間)
    ...Array.from({ length: n_signals }, (_, i): uPlot.Series => ({
      label: n_signals === 1 ? scopeId : `${scopeId}[${i}]`,
      stroke: SCOPE_COLORS[i % SCOPE_COLORS.length],
      width: 1.5,
      points: { show: false },
    })),
  ];
  return {
    width: 400, // ResizeObserver で実寸に追従するため初期値で良い
    height: 192, // h-48 = 12rem = 192px
    series,
    scales: {
      x: { time: false }, // シミュレーション時間 [s] は時刻として扱わない (= 数値軸)
    },
    axes: [
      { stroke: "#94a3b8", grid: { stroke: "#e2e8f0" }, label: "t [s]" },
      { stroke: "#94a3b8", grid: { stroke: "#e2e8f0" } },
    ],
    legend: { show: true, live: false },
    cursor: { show: true, drag: { x: true, y: false } },
  };
}

/**
 * Scope ストリームを uPlot で時系列描画するコンポーネント。
 *
 * 信号数 ``buffer.n_signals`` は最初のサンプルを受信するまで 0 で、その間は
 * placeholder (= 「No data」) を表示する。
 */
export function ScopeView({ scopeId, buffer }: ScopeViewProps): JSX.Element {
  // signals 数が変わったら uPlot を再生成する必要があるので、options を memo
  // 依存に含める (= options 参照変更で UPlotChart が destroy → 再生成)。
  const options = useMemo(
    () => buildOptions(scopeId, Math.max(buffer.n_signals, 1)),
    [scopeId, buffer.n_signals],
  );
  // data は buffer の length が変わるたびに新参照を作る (= setData が走る)。
  // ``buffer`` 参照だけでなく ``buffer.length`` を依存に明示することで、in-place
  // 追記 (= buffer 参照は変わったが内部 typed array 参照は同一) でも data の
  // 再構成 trigger が確実に走るよう意図を露出させる。
  const data = useMemo(
    () => buildAlignedData(buffer),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- length 変化で再計算
    [buffer, buffer.length],
  );

  if (buffer.length === 0) {
    return (
      <div className="flex h-48 w-full items-center justify-center border border-slate-200 bg-white text-[12px] text-slate-400">
        {scopeId}: (no data yet)
      </div>
    );
  }

  return (
    <div className="relative h-48 w-full border border-slate-200 bg-white">
      <UPlotChart options={options} data={data} className="absolute inset-0" />
    </div>
  );
}
