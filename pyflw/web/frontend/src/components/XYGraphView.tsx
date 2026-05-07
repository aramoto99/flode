// XYGraph の可視化: 入力 0 = x, 入力 1 = y のパラメトリック散布線プロット。
// ScopeView と同じ ScopeBuffer を受けるが、時間軸ではなく x-y 平面に描く。

import { useEffect, useRef } from "react";

import type { ScopeBuffer } from "../store/appStore";

interface XYGraphViewProps {
  scopeId: string;
  buffer: ScopeBuffer;
  xLabel?: string;
  yLabel?: string;
}

export function XYGraphView({
  scopeId,
  buffer,
  xLabel = "x",
  yLabel = "y",
}: XYGraphViewProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const { width, height } = canvas.getBoundingClientRect();
    if (width === 0 || height === 0) return;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);

    if (buffer.values.length < 2) {
      ctx.fillStyle = "#64748b";
      ctx.font = "12px sans-serif";
      ctx.fillText("(no data yet)", 8, 16);
      return;
    }

    const padding = 28;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;

    let xMin = Infinity;
    let xMax = -Infinity;
    let yMin = Infinity;
    let yMax = -Infinity;
    for (const row of buffer.values) {
      const x = row[0];
      const y = row[1];
      if (x === undefined || y === undefined) continue;
      if (x < xMin) xMin = x;
      if (x > xMax) xMax = x;
      if (y < yMin) yMin = y;
      if (y > yMax) yMax = y;
    }
    if (
      !Number.isFinite(xMin) ||
      !Number.isFinite(xMax) ||
      !Number.isFinite(yMin) ||
      !Number.isFinite(yMax)
    ) {
      return;
    }
    const xRange = xMax - xMin || 1;
    const yRange = yMax - yMin || 1;

    // 軸 (X=0, Y=0 を含むなら描画)
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 0.6;
    if (xMin <= 0 && xMax >= 0) {
      const x0 = padding + ((0 - xMin) / xRange) * plotW;
      ctx.beginPath();
      ctx.moveTo(x0, padding);
      ctx.lineTo(x0, padding + plotH);
      ctx.stroke();
    }
    if (yMin <= 0 && yMax >= 0) {
      const y0 = padding + plotH - ((0 - yMin) / yRange) * plotH;
      ctx.beginPath();
      ctx.moveTo(padding, y0);
      ctx.lineTo(padding + plotW, y0);
      ctx.stroke();
    }

    // 枠
    ctx.strokeStyle = "#e2e8f0";
    ctx.lineWidth = 1;
    ctx.strokeRect(padding, padding, plotW, plotH);

    // パラメトリック折れ線
    ctx.beginPath();
    ctx.strokeStyle = "#2563eb";
    ctx.lineWidth = 1.5;
    for (let i = 0; i < buffer.values.length; i += 1) {
      const row = buffer.values[i];
      if (!row) continue;
      const x = row[0];
      const y = row[1];
      if (x === undefined || y === undefined) continue;
      const px = padding + ((x - xMin) / xRange) * plotW;
      const py = padding + plotH - ((y - yMin) / yRange) * plotH;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();

    // 最新点をマーカー
    const last = buffer.values[buffer.values.length - 1];
    if (last && last[0] !== undefined && last[1] !== undefined) {
      const px = padding + ((last[0] - xMin) / xRange) * plotW;
      const py = padding + plotH - ((last[1] - yMin) / yRange) * plotH;
      ctx.beginPath();
      ctx.fillStyle = "#dc2626";
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
    }

    // ラベル
    ctx.fillStyle = "#64748b";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(scopeId, 8, 12);
    ctx.textAlign = "center";
    ctx.fillText(xLabel, padding + plotW / 2, height - 4);
    ctx.save();
    ctx.translate(10, padding + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText(yLabel, 0, 0);
    ctx.restore();
    ctx.textAlign = "right";
    ctx.fillText(
      `[${xMin.toFixed(2)}, ${xMax.toFixed(2)}] × [${yMin.toFixed(2)}, ${yMax.toFixed(2)}]`,
      width - 8,
      12,
    );
  }, [scopeId, buffer, xLabel, yLabel]);

  return (
    <div className="relative h-56 w-full border border-slate-200 bg-white">
      <canvas ref={canvasRef} className="absolute inset-0" />
    </div>
  );
}
