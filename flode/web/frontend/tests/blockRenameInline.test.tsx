// SPEC-0022 §機能要件 1/3/4: キャンバス id ラベルの inline rename テスト。
// dblclick / F2 (renameRequest) 起動、Enter 確定 / Escape 取消、IME composition
// 中の Enter 無視、検証 NG 時のエラー表示と編集維持を実 store で検証する。

import { cleanup, fireEvent, render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BlockIdLabel } from "../src/components/BlockNodeView";
import { useAppStore } from "../src/store/appStore";
import type { FlwModel } from "../src/types/api";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

const GAIN = "flode.blocks.mathops.Gain";

function baseModel(): FlwModel {
  return {
    schema_version: "0.10",
    simulator: {
      t_end: 10,
      dt: 0.01,
      solver: "RK45",
      rtol: 1e-3,
      atol: 1e-6,
      dt_base: null,
    },
    blocks: [
      { id: "Gain_0", type: GAIN, params: { k: 2 } },
      { id: "Gain_1", type: GAIN, params: { k: 3 } },
    ],
    connections: [],
    layout: { Gain_0: { x: 0, y: 0 }, Gain_1: { x: 100, y: 0 } },
  };
}

beforeEach(() => {
  useAppStore.setState({
    editingModel: baseModel(),
    editingPath: [],
    history: { past: [], future: [] },
    lastMergeKey: null,
    dirty: false,
    renameRequest: null,
  });
});

afterEach(() => {
  cleanup();
  useAppStore.setState({
    editingModel: null,
    editingPath: [],
    history: { past: [], future: [] },
    renameRequest: null,
  });
});

function blockIds(): string[] {
  return useAppStore.getState().editingModel!.blocks.map((b) => b.id);
}

function startEditing(): HTMLInputElement {
  fireEvent.doubleClick(screen.getByTestId("block-id-label"));
  return screen.getByTestId("block-id-input") as HTMLInputElement;
}

describe("BlockIdLabel — inline rename", () => {
  it("通常表示では id テキストのみ (input なし)", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    expect(screen.getByTestId("block-id-label").textContent).toBe("Gain_0");
    expect(screen.queryByTestId("block-id-input")).toBeNull();
  });

  it("dblclick で編集モードに入り、Enter で確定して model が rename される", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    expect(input.value).toBe("Gain_0");
    fireEvent.change(input, { target: { value: "トルクゲイン" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(blockIds()).toEqual(["トルクゲイン", "Gain_1"]);
    expect(screen.queryByTestId("block-id-input")).toBeNull();
  });

  it("Escape で取消 (model 不変、編集モード終了)", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "変更途中" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(blockIds()).toEqual(["Gain_0", "Gain_1"]);
    expect(screen.queryByTestId("block-id-input")).toBeNull();
  });

  it("blur で確定される", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "g" } });
    fireEvent.blur(input);
    expect(blockIds()).toEqual(["g", "Gain_1"]);
  });

  it("IME composition 中の Enter は確定しない (ADR-0071 §(11))", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "そくど" } });
    fireEvent.keyDown(input, { key: "Enter" }); // 変換確定の Enter
    expect(blockIds()).toEqual(["Gain_0", "Gain_1"]); // rename されない
    expect(screen.getByTestId("block-id-input")).toBeTruthy(); // 編集継続
    fireEvent.compositionEnd(input);
    fireEvent.change(input, { target: { value: "速度" } });
    fireEvent.keyDown(input, { key: "Enter" }); // composition 後の Enter で確定
    expect(blockIds()).toEqual(["速度", "Gain_1"]);
  });

  it("検証 NG (重複) は確定を拒否し、エラー表示 + 編集モード維持", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    fireEvent.change(input, { target: { value: "Gain_1" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(blockIds()).toEqual(["Gain_0", "Gain_1"]);
    expect(screen.getByTestId("block-id-input")).toBeTruthy();
    expect(screen.getByTestId("block-id-error").textContent).toBe(
      "diagram.rename.duplicate",
    );
    // 再入力でエラーが消え、確定できる
    fireEvent.change(input, { target: { value: "g2" } });
    expect(screen.queryByTestId("block-id-error")).toBeNull();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(blockIds()).toEqual(["g2", "Gain_1"]);
  });

  it("旧 id と同一で確定 → no-op で編集モードを閉じる", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    const input = startEditing();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(blockIds()).toEqual(["Gain_0", "Gain_1"]);
    expect(screen.queryByTestId("block-id-input")).toBeNull();
    expect(useAppStore.getState().history.past).toHaveLength(0);
  });

  it("renameRequest (F2 経由) で編集モードに入る", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    act(() => {
      useAppStore.getState().requestRename("Gain_0");
    });
    expect(screen.getByTestId("block-id-input")).toBeTruthy();
  });

  it("他ブロック宛の renameRequest では編集モードに入らない", () => {
    render(<BlockIdLabel blockId="Gain_0" />);
    act(() => {
      useAppStore.getState().requestRename("Gain_1");
    });
    expect(screen.queryByTestId("block-id-input")).toBeNull();
  });
});
