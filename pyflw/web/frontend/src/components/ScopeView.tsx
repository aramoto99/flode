// Scope ストリームの可視化 (ADR-0012 §(3))。
// Phase 2 はシンプルな表形式表示 + 簡易プロット (canvas 自前)。
// uPlot は別途依存追加するが、Phase 2 では canvas ベースの最小プロットで足りる
// (表現力が必要になったら uPlot に置き換える前提で API は分離)。

import { useEffect, useRef } from "react";

import type { ScopeBuffer } from "../store/appStore";

interface ScopeViewProps {
  scopeId: string;
  buffer: ScopeBuffer;
}

export function ScopeView({ scopeId, buffer }: ScopeViewProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width, height } = canvas.getBoundingClientRect();
    // 親が ``display:none`` 等で 0 サイズの場合は描画スキップ (NaN を防ぐ)。
    if (width === 0 || height === 0) return;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);

    if (buffer.times.length < 2 || buffer.values.length < 2) {
      ctx.fillStyle = "#6b7280";
      ctx.font = "12px sans-serif";
      ctx.fillText("(no data yet)", 8, 16);
      return;
    }

    const padding = 24;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;
    const tMin = buffer.times[0];
    const tMax = buffer.times[buffer.times.length - 1];
    const tRange = tMax - tMin || 1;

    const nPorts = buffer.values[0]?.length ?? 0;
    if (nPorts === 0) return;

    let yMin = Infinity;
    let yMax = -Infinity;
    for (const row of buffer.values) {
      for (const v of row) {
        if (v < yMin) yMin = v;
        if (v > yMax) yMax = v;
      }
    }
    if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) {
      return;
    }
    const yRange = yMax - yMin || 1;

    const colors = ["#2563eb", "#dc2626", "#16a34a", "#ca8a04"];
    for (let p = 0; p < nPorts; p += 1) {
      ctx.beginPath();
      ctx.strokeStyle = colors[p % colors.length] ?? "#000";
      ctx.lineWidth = 1.5;
      for (let i = 0; i < buffer.times.length; i += 1) {
        const x = padding + ((buffer.times[i]! - tMin) / tRange) * plotW;
        const v = buffer.values[i]?.[p] ?? 0;
        const y = padding + plotH - ((v - yMin) / yRange) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    ctx.fillStyle = "#6b7280";
    ctx.font = "11px sans-serif";
    ctx.fillText(`${scopeId}  t=[${tMin.toFixed(2)}, ${tMax.toFixed(2)}]`, 8, 14);
    ctx.fillText(`y=[${yMin.toFixed(3)}, ${yMax.toFixed(3)}]`, 8, height - 6);
  }, [scopeId, buffer]);

  return (
    <div className="relative h-48 w-full border border-gray-200 bg-white">
      <canvas ref={canvasRef} className="absolute inset-0" />
    </div>
  );
}
