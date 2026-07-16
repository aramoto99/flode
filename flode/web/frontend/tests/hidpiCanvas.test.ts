// HiDPI canvas サイジングのロジックを検証する。
// バグ: XYGraphView が devicePixelRatio を考慮せず canvas のバッキングストアを
// CSS px 等倍で作っていたため、高 DPI ディスプレイ (dpr > 1) で拡大表示され
// ピンボケしていた。sizeCanvasToDisplay はバッキングストアを CSS px × dpr に
// し、以後の描画を CSS px 座標で行えるよう ctx を dpr 倍スケールする。

import { describe, expect, it, vi } from "vitest";

import { sizeCanvasToDisplay } from "../src/lib/hidpiCanvas";

interface CanvasLike {
  width: number;
  height: number;
}

function makeCtx(): { scale: ReturnType<typeof vi.fn> } {
  return { scale: vi.fn() };
}

describe("sizeCanvasToDisplay", () => {
  it("sizes the backing store by devicePixelRatio so HiDPI is not blurry", () => {
    const canvas: CanvasLike = { width: 0, height: 0 };
    const ctx = makeCtx();
    sizeCanvasToDisplay(
      canvas as unknown as HTMLCanvasElement,
      ctx as unknown as CanvasRenderingContext2D,
      300,
      120,
      2,
    );
    // バッキングストアは CSS px × dpr
    expect(canvas.width).toBe(600); // 300 * 2
    expect(canvas.height).toBe(240); // 120 * 2
    // 描画座標を CSS px のまま維持するため dpr 倍スケール
    expect(ctx.scale).toHaveBeenCalledWith(2, 2);
  });

  it("sets the backing store to CSS px dimensions when dpr=1", () => {
    const canvas: CanvasLike = { width: 0, height: 0 };
    const ctx = makeCtx();
    sizeCanvasToDisplay(
      canvas as unknown as HTMLCanvasElement,
      ctx as unknown as CanvasRenderingContext2D,
      300,
      120,
      1,
    );
    expect(canvas.width).toBe(300);
    expect(canvas.height).toBe(120);
    expect(ctx.scale).toHaveBeenCalledWith(1, 1);
  });

  it("rounds fractional backing-store dimensions (e.g. 1.5x scaling)", () => {
    const canvas: CanvasLike = { width: 0, height: 0 };
    const ctx = makeCtx();
    sizeCanvasToDisplay(
      canvas as unknown as HTMLCanvasElement,
      ctx as unknown as CanvasRenderingContext2D,
      301,
      121,
      1.5,
    );
    expect(canvas.width).toBe(452); // Math.round(301 * 1.5)
    expect(canvas.height).toBe(182); // Math.round(121 * 1.5)
    expect(ctx.scale).toHaveBeenCalledWith(1.5, 1.5);
  });

  it("falls back to dpr=1 for non-positive / non-finite ratios", () => {
    const canvas: CanvasLike = { width: 0, height: 0 };
    const ctx = makeCtx();
    sizeCanvasToDisplay(
      canvas as unknown as HTMLCanvasElement,
      ctx as unknown as CanvasRenderingContext2D,
      300,
      120,
      0,
    );
    expect(canvas.width).toBe(300);
    expect(canvas.height).toBe(120);
    expect(ctx.scale).toHaveBeenCalledWith(1, 1);
  });

  it("defaults to window.devicePixelRatio when dpr is omitted", () => {
    const spy = vi
      .spyOn(window, "devicePixelRatio", "get")
      .mockReturnValue(3);
    try {
      const canvas: CanvasLike = { width: 0, height: 0 };
      const ctx = makeCtx();
      sizeCanvasToDisplay(
        canvas as unknown as HTMLCanvasElement,
        ctx as unknown as CanvasRenderingContext2D,
        300,
        120,
      );
      expect(canvas.width).toBe(900); // 300 * 3
      expect(canvas.height).toBe(360); // 120 * 3
      expect(ctx.scale).toHaveBeenCalledWith(3, 3);
    } finally {
      spy.mockRestore();
    }
  });
});
