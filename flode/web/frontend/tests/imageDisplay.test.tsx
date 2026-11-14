// SPEC-0034 F-5〜F-7 / R-4: 画像表示ブロック (ImageDisplay) のフロント側と
// モデル設定の「実時間に同期」チェックボックス。

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ImageDisplayLive,
  imageFrameToRgba,
} from "../src/components/BlockNodeView";
import { ModelSettingsModal } from "../src/components/ModelSettingsModal";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel, ImageFrame } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

/** uint8 列を base64 にする (atob の逆)。 */
function b64(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes));
}

function frame(overrides: Partial<ImageFrame> = {}): ImageFrame {
  return {
    block_id: "screen",
    t: 0.5,
    height: 1,
    width: 2,
    channels: 3,
    data: b64([10, 20, 30, 40, 50, 60]),
    ...overrides,
  };
}

function makeModel(realtime?: boolean): FlwModel {
  return {
    schema_version: "0.15",
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-6,
      atol: 1e-9,
      dt_base: null,
      ...(realtime === undefined ? {} : { realtime }),
    },
    blocks: [],
    connections: [],
    layout: {},
  };
}

beforeEach(() => {
  useAppStore.setState({ imageFrames: {} });
});

afterEach(() => {
  cleanup();
});

describe("imageFrameToRgba", () => {
  it("expands RGB to RGBA with opaque alpha", () => {
    expect(Array.from(imageFrameToRgba(frame()) ?? [])).toEqual([
      10, 20, 30, 255, 40, 50, 60, 255,
    ]);
  });

  it("expands gray to RGBA", () => {
    const gray = frame({ channels: 1, data: b64([7, 200]) });
    expect(Array.from(imageFrameToRgba(gray) ?? [])).toEqual([
      7, 7, 7, 255, 200, 200, 200, 255,
    ]);
  });

  it.each([
    ["length mismatch", { data: b64([1, 2, 3]) }],
    ["unsupported channels", { channels: 4, data: b64([1, 2, 3, 4, 5, 6, 7, 8]) }],
    ["empty image", { width: 0, data: "" }],
    ["invalid base64", { data: "@@@" }],
  ])("returns null for %s", (_label, overrides) => {
    expect(imageFrameToRgba(frame(overrides))).toBeNull();
  });
});

describe("ImageDisplayLive", () => {
  it("shows a placeholder before the first frame", () => {
    render(<ImageDisplayLive blockId="screen" />);
    expect(screen.queryByTestId("image-display-canvas")).toBeNull();
    expect(screen.getByText("— — —")).toBeTruthy();
  });

  it("draws a canvas once a frame arrives", () => {
    // jsdom は 2d context 非対応。描画呼び出しを捕まえる最小の偽物を返す
    const putImageData = vi.fn();
    const spy = vi
      .spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue({ putImageData } as unknown as CanvasRenderingContext2D);
    vi.stubGlobal(
      "ImageData",
      class {
        constructor(
          public data: Uint8ClampedArray,
          public width: number,
          public height: number,
        ) {}
      },
    );
    try {
      useAppStore.setState({ imageFrames: { screen: frame() } });
      render(<ImageDisplayLive blockId="screen" />);
      const canvas = screen.getByTestId("image-display-canvas") as HTMLCanvasElement;
      expect([canvas.width, canvas.height]).toEqual([2, 1]);
      expect(putImageData).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
      vi.unstubAllGlobals();
    }
  });
});

describe("image_frame stream handling", () => {
  it("stores the latest frame per block and clears it on the next run", () => {
    const { handleStreamMessage } = useAppStore.getState();
    handleStreamMessage({ type: "image_frame", ...frame({ t: 0.1 }) });
    handleStreamMessage({ type: "image_frame", ...frame({ t: 0.2 }) });
    const stored = useAppStore.getState().imageFrames.screen;
    expect(stored?.t).toBe(0.2);
    expect(stored).not.toHaveProperty("type");

    useAppStore.getState().startedSimulation("next-run");
    expect(useAppStore.getState().imageFrames).toEqual({});
  });

  it("replaceImageFrames merges results from GET /results", () => {
    useAppStore.getState().replaceImageFrames({ screen: frame({ t: 9 }) });
    expect(useAppStore.getState().imageFrames.screen?.t).toBe(9);
  });
});

describe("ModelSettingsModal realtime checkbox", () => {
  it("writes realtime: true when checked", () => {
    useAppStore.setState({ editingModel: makeModel(), editingPath: [] });
    render(<ModelSettingsModal onClose={() => {}} />);
    const box = screen.getByTestId("model-settings-realtime") as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    fireEvent.click(screen.getByTestId("model-settings-save"));
    expect(useAppStore.getState().editingModel?.simulator.realtime).toBe(true);
  });

  it("drops the key from the saved JSON when unchecked", () => {
    useAppStore.setState({ editingModel: makeModel(true), editingPath: [] });
    render(<ModelSettingsModal onClose={() => {}} />);
    const box = screen.getByTestId("model-settings-realtime") as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    fireEvent.click(screen.getByTestId("model-settings-save"));
    const sim = useAppStore.getState().editingModel?.simulator;
    expect(JSON.parse(JSON.stringify(sim))).not.toHaveProperty("realtime");
  });
});
