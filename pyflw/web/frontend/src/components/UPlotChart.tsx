// ADR-0023 §Decision §(2): uPlot の薄い React ラッパ。
// `uplot-react` は依存削減のため使わず、自前で最小実装する。
//
// 設計:
//   - mount 時に ``new uPlot(opts, data, root)`` を 1 回。
//   - ``data`` prop が参照変更したら ``setData(data)`` を呼ぶ (= 差分更新、配列は再作成
//     しないと React の依存比較で気付けないので呼び出し側が新参照を渡すこと)。
//   - ``options`` prop が参照変更したら destroy → 再生成 (オプション変更は uPlot の
//     仕様で全再構築が必要)。
//   - ResizeObserver で親コンテナのサイズ追従 (ADR-0023 §Decision §(2))。
//
// React 18 strict mode で useEffect が double-invoke されるが、cleanup で確実に
// destroy しているので問題なし。

import uPlot from "uplot";
import { useEffect, useRef } from "react";
import "uplot/dist/uPlot.min.css";

export interface UPlotChartProps {
  /** uPlot 初期化オプション。参照が変わると uPlot を再生成。 */
  options: uPlot.Options;
  /** 表示データ。``[xs, ys1, ys2, ...]`` の AlignedData。参照変更で setData。 */
  data: uPlot.AlignedData;
  /** 親コンテナの className。サイズ・余白制御は呼び出し側に委ねる。 */
  className?: string;
}

/**
 * 軽量 uPlot React ラッパ。
 *
 * 親が ``data`` / ``options`` の参照を更新するたびに uPlot へ反映する。
 * チャートの DOM 要素は内部の ``<div ref>`` に attach される。
 */
export function UPlotChart({
  options,
  data,
  className,
}: UPlotChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<uPlot | null>(null);
  const lastOptionsRef = useRef<uPlot.Options | null>(null);
  const lastDataRef = useRef<uPlot.AlignedData | null>(null);

  // mount + options 変更時の (再) 生成
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    // 既存 instance があれば破棄してから作り直す
    instanceRef.current?.destroy();
    const inst = new uPlot(options, data, root);
    instanceRef.current = inst;
    lastOptionsRef.current = options;
    lastDataRef.current = data;
    return () => {
      inst.destroy();
      if (instanceRef.current === inst) instanceRef.current = null;
    };
  }, [options]); // eslint-disable-line react-hooks/exhaustive-deps -- data は別 effect

  // data 参照が変わったら setData (options 再生成の effect が新しい data で
  // 構築済みの場合は呼ばない、= lastDataRef で判定)
  useEffect(() => {
    const inst = instanceRef.current;
    if (!inst) return;
    if (lastDataRef.current === data) return;
    inst.setData(data);
    lastDataRef.current = data;
  }, [data]);

  // 親サイズ追従 (ResizeObserver)
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const ro = new ResizeObserver(() => {
      const inst = instanceRef.current;
      if (!inst) return;
      const { width, height } = root.getBoundingClientRect();
      if (width > 0 && height > 0) {
        inst.setSize({ width, height });
      }
    });
    ro.observe(root);
    return () => ro.disconnect();
  }, []);

  // ADR-0044 §論点 7: マウスホイールで X 軸 zoom (カーソル位置を中心に拡大/縮小)。
  // Shift 押下時は Y 軸 zoom。Ctrl 押下時はブラウザのページズームに譲る。
  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    const ZOOM_FACTOR = 1.2; // 1 notch = 20% zoom in/out

    const handler = (e: WheelEvent): void => {
      // Ctrl は browser のページズーム / OS のスクロール拡大に譲る
      if (e.ctrlKey || e.metaKey) return;
      const inst = instanceRef.current;
      if (!inst) return;
      e.preventDefault();

      // uPlot のプロット領域 (axes 外) 座標に変換
      const rect = root.getBoundingClientRect();
      const offsetX = e.clientX - rect.left;
      const offsetY = e.clientY - rect.top;

      const axisKey = e.shiftKey ? "y" : "x";
      const scale = inst.scales[axisKey];
      if (!scale || scale.min == null || scale.max == null) return;

      // 拡大係数: deltaY > 0 (= 下スクロール) で zoom out、deltaY < 0 で zoom in
      const factor = e.deltaY > 0 ? ZOOM_FACTOR : 1 / ZOOM_FACTOR;

      // カーソル位置の data 値を取得 (= zoom 中心)
      const cursorVal =
        axisKey === "x"
          ? inst.posToVal(offsetX, "x")
          : inst.posToVal(offsetY, "y");
      if (cursorVal == null || !Number.isFinite(cursorVal)) return;

      const newMin = cursorVal - (cursorVal - scale.min) * factor;
      const newMax = cursorVal + (scale.max - cursorVal) * factor;
      if (!Number.isFinite(newMin) || !Number.isFinite(newMax)) return;
      if (newMax <= newMin) return;

      inst.setScale(axisKey, { min: newMin, max: newMax });
    };

    // `passive: false` で preventDefault を効かせる
    root.addEventListener("wheel", handler, { passive: false });
    return () => root.removeEventListener("wheel", handler);
  }, []);

  return <div ref={containerRef} className={className} />;
}
